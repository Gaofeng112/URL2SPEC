"""使用 Playwright 打开页面并捕获 XHR/Fetch 网络请求。"""

import base64
import hashlib
import json
import threading
from datetime import datetime
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from capture.sanitizer import safe_preview_body, sanitize_headers

# 按 URL 路径后缀识别的静态资源扩展名，用于过滤非业务接口。
STATIC_EXTENSIONS = (
    ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".map", ".webp", ".mp4", ".mp3",
)

# VIP 解密默认 key（可按需调整/外部传入）。
VIP_DEFAULT_KEY = "VIP4.2.0"


def vip_decrypt(data, key=VIP_DEFAULT_KEY):
    """vip解密（按用户提供的 Python 版本实现）。"""
    content = base64.b64decode(data)
    key = hashlib.md5(hashlib.md5(key.encode("utf-8")).hexdigest().encode("utf-8")).hexdigest()
    x = 0
    length = len(content)
    result = b""
    for i in range(length):
        if x == 32:
            x = 0
        char = key[x]
        result += bytes([content[i] ^ ord(char)])
        x += 1
    return result.decode("utf-8")


def _short20(value):
    if value is None:
        return ""
    try:
        text = value if isinstance(value, str) else str(value)
    except Exception:
        text = repr(value)
    return text[:20]


def _looks_like_base64(s, min_len=8):
    if not isinstance(s, str):
        return False
    raw = s.strip()
    if len(raw) < min_len:
        return False
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\r\n-_"
    return all(c in allowed for c in raw)


def _normalize_base64(s):
    raw = s.strip().replace("\n", "").replace("\r", "")
    raw = raw.replace("-", "+").replace("_", "/")
    pad = (-len(raw)) % 4
    if pad:
        raw += "=" * pad
    return raw


def _iter_strings(obj, path="$", depth=0, max_depth=6, max_items=2000):
    """遍历 JSON-like 对象里的字符串值，产出 (path, value)。"""
    if max_items <= 0:
        return
    if depth > max_depth:
        return
    if isinstance(obj, str):
        yield (path, obj)
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_strings(v, f"{path}.{k}", depth + 1, max_depth, max_items - 1)
        return
    if isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _iter_strings(v, f"{path}[{i}]", depth + 1, max_depth, max_items - 1)
        return


def _try_vip_decrypt_string(value, key=VIP_DEFAULT_KEY, force=False):
    """对疑似 base64 字符串尝试 VIP 解密；成功返回明文，否则返回 None。"""
    min_len = 4 if force else 8
    if not _looks_like_base64(value, min_len=min_len):
        return None
    try:
        plaintext = vip_decrypt(_normalize_base64(value), key=key)
    except Exception:
        return None
    if not isinstance(plaintext, str) or not plaintext:
        return None
    return plaintext


def _scan_vip_decrypt(body):
    """扫描 JSON 响应，优先解密 data 等常见密文字段。"""
    logs = []
    if isinstance(body, dict):
        priority_keys = ("data", "content", "result", "payload", "encrypt")
        for key in priority_keys:
            val = body.get(key)
            if isinstance(val, str):
                plaintext = _try_vip_decrypt_string(val, force=True)
                if plaintext:
                    logs.append((f"$.{key}", val, plaintext))
        for json_path, s in _iter_strings(body):
            if any(json_path.endswith(f".{k}") for k in priority_keys):
                continue
            plaintext = _try_vip_decrypt_string(s)
            if plaintext:
                logs.append((json_path, s, plaintext))
    return logs


def safe_get_post_data(request):
    """安全读取请求体，避免 Playwright 对二进制 POST 做 UTF-8 解码时报错。

    Args:
        request: Playwright ``Request`` 对象。

    Returns:
        文本请求体；二进制内容以 ``[binary:...]`` 标记；无 body 时返回 ``None``。
    """
    try:
        data = request.post_data
        if data is not None:
            return data
    except UnicodeDecodeError:
        pass
    except Exception:
        return None

    try:
        buf = request.post_data_buffer
        if not buf:
            return None
        try:
            return buf.decode("utf-8")
        except UnicodeDecodeError:
            encoded = base64.b64encode(buf).decode("ascii")
            preview = encoded[:120] + ("..." if len(encoded) > 120 else "")
            return f"[binary:{preview}]"
    except Exception:
        return None


def post_data_dedup_key(request):
    """生成用于去重的 POST 体摘要。

    Args:
        request: Playwright ``Request`` 对象。

    Returns:
        字符串键片段。
    """
    body = safe_get_post_data(request)
    if body is not None:
        return body
    try:
        buf = request.post_data_buffer
        if buf:
            return hashlib.md5(buf).hexdigest()
    except Exception:
        pass
    return ""


def is_static_resource(url):
    """判断 URL 是否指向静态资源文件。

    Args:
        url: 完整请求 URL。

    Returns:
        若路径以静态资源扩展名结尾则返回 ``True``。
    """
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in STATIC_EXTENSIONS)


def _wait_for_interactive_stop(page, stop_event, poll_ms=300):
    """在交互模式下轮询等待用户结束信号，同时保持 Playwright 事件循环活跃。"""
    while not stop_event.is_set():
        page.wait_for_timeout(poll_ms)


def capture_api_requests(page_url, wait_seconds=8, interactive=True):
    """打开目标页面并采集 XHR/Fetch 请求记录。

    默认以有头浏览器交互式采集：用户可在页面中操作触发接口，回到终端按
    Enter 结束。若 ``interactive=False``，则在页面加载后固定等待
    ``wait_seconds`` 秒。

    对 JSON 响应中的常见密文字段尝试 VIP 解密，成功时打印解密前/后各 20 个字符。

    Args:
        page_url: 待分析的页面 URL。
        wait_seconds: 非交互模式下页面加载完成后的额外等待秒数。
        interactive: 是否启用交互式采集（终端按 Enter 结束）。

    Returns:
        接口记录列表。每条记录包含 method、url、headers、body 预览等字段。
    """
    api_records = []
    seen = set()
    capturing = True
    stop_event = threading.Event()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=50)

        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        def handle_response(response):
            """Playwright 响应回调：过滤、去重并序列化单条接口记录。"""
            if not capturing:
                return

            try:
                request = response.request

                if request.resource_type not in ["xhr", "fetch"]:
                    return

                if is_static_resource(request.url):
                    return

                post_body = safe_get_post_data(request)
                key = f"{request.method}:{request.url}:{post_data_dedup_key(request)}"
                if key in seen:
                    return
                seen.add(key)

                response_headers = response.headers
                content_type = response_headers.get("content-type", "")

                record = {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "method": request.method,
                    "url": request.url,
                    "resource_type": request.resource_type,
                    "status": response.status,
                    "request_headers": sanitize_headers(request.headers),
                    "request_body": post_body,
                    "response_headers": sanitize_headers(response_headers),
                    "content_type": content_type,
                    "response_body_preview": None,
                    "decrypt_preview": [],
                }

                try:
                    body = None
                    if "application/json" in content_type:
                        body = response.json()
                    elif "text" in content_type or "html" in content_type:
                        text = response.text()
                        record["response_body_preview"] = text[:1000]
                        if text.strip().startswith("{"):
                            try:
                                body = json.loads(text)
                                record["response_body_preview"] = safe_preview_body(body)
                            except Exception:
                                body = None
                    else:
                        record["response_body_preview"] = "[非文本响应，已忽略]"

                    if body is not None:
                        if "response_body_preview" not in record or record["response_body_preview"] is None:
                            record["response_body_preview"] = safe_preview_body(body)
                        try:
                            decrypt_logs = []
                            for json_path, cipher, plaintext in _scan_vip_decrypt(body):
                                before20 = _short20(cipher)
                                after20 = _short20(plaintext)
                                print(f"[解密] 来源: vip_decrypt {json_path}")
                                print(f"  解密前(20字): {before20}")
                                print(f"  解密后(20字): {after20}")
                                decrypt_logs.append(
                                    {
                                        "source": f"vip_decrypt {json_path}",
                                        "before20": before20,
                                        "after20": after20,
                                        "after_preview": plaintext[:500],
                                    }
                                )
                            record["decrypt_preview"] = decrypt_logs
                        except Exception as e:
                            record["decrypt_preview"] = [
                                {"source": "vip_decrypt", "error": str(e)[:200]}
                            ]
                    elif record.get("response_body_preview") is None:
                        record["response_body_preview"] = "[非文本响应，已忽略]"
                except Exception as e:
                    record["response_body_preview"] = f"[响应体读取失败：{str(e)}]"

                api_records.append(record)
                print(f"[接口] {request.method} {request.url} {response.status}")
            except Exception as e:
                print(f"[警告] 跳过无法处理的响应：{e}")

        page.on("response", handle_response)

        if interactive:
            threading.Thread(
                target=lambda: (
                    input("按 Enter 键结束采集..."),
                    stop_event.set(),
                ),
                daemon=True,
            ).start()
            print("=" * 60)
            print("交互式接口采集已启动")
            print("请在浏览器中操作页面以触发 XHR/Fetch 请求")
            print("若页面存在解密逻辑，将打印解密前/后各 20 个字符")
            print("完成后返回此终端，按 Enter 键结束采集")
            print("=" * 60)

        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
            if interactive:
                _wait_for_interactive_stop(page, stop_event)
            else:
                page.wait_for_timeout(wait_seconds * 1000)
        except Exception as e:
            print(f"页面访问异常：{e}")
        finally:
            capturing = False
            try:
                page.wait_for_timeout(500)
            except Exception:
                pass
            browser.close()

    print(f"采集结束，共捕获 {len(api_records)} 条 XHR/Fetch 接口")
    return api_records
