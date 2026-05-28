"""使用 Playwright 打开页面并捕获 XHR/Fetch 网络请求。"""

import base64
import fnmatch
import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path
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


def _normalize_url_filters(url_filters):
    if not url_filters:
        return []
    if isinstance(url_filters, str):
        values = url_filters.split(",")
    else:
        values = []
        for item in url_filters:
            values.extend(str(item).split(","))
    return [item.strip() for item in values if item and item.strip()]


def _url_matches_filter(url, pattern):
    parsed = urlparse(url)
    path = parsed.path or "/"
    normalized_path = path.lstrip("/")
    normalized_pattern = pattern.lstrip("/")

    if pattern.startswith(("http://", "https://")):
        return fnmatch.fnmatch(url, pattern)

    return (
        fnmatch.fnmatch(path, pattern)
        or fnmatch.fnmatch(path, f"/{normalized_pattern}")
        or fnmatch.fnmatch(normalized_path, normalized_pattern)
    )


def url_matches_filters(url, url_filters):
    """判断 URL 是否匹配任一采集过滤规则；无规则时默认通过。"""
    filters = _normalize_url_filters(url_filters)
    if not filters:
        return True
    return any(_url_matches_filter(url, pattern) for pattern in filters)


def _wait_for_interactive_stop(page, stop_event, poll_ms=300):
    """在交互模式下轮询等待用户结束信号，同时保持 Playwright 事件循环活跃。"""
    while not stop_event.is_set():
        page.wait_for_timeout(poll_ms)


def _target_cookie_url(page_url):
    parsed = urlparse(page_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"目标 URL 不合法，无法推断 cookie 作用域：{page_url}")
    return f"{parsed.scheme}://{parsed.netloc}/"


def _normalize_same_site(value):
    if not value:
        return None
    normalized = str(value).strip().lower()
    mapping = {
        "lax": "Lax",
        "strict": "Strict",
        "none": "None",
        "no_restriction": "None",
        "no-restriction": "None",
        "no restriction": "None",
        "unspecified": None,
    }
    return mapping.get(normalized)


def _normalize_cookie(cookie, page_url):
    if not isinstance(cookie, dict):
        return None

    name = cookie.get("name")
    value = cookie.get("value")
    if name is None or value is None:
        return None

    normalized = {
        "name": str(name),
        "value": str(value),
    }

    if cookie.get("url"):
        normalized["url"] = str(cookie["url"])
    elif cookie.get("domain"):
        normalized["domain"] = str(cookie["domain"])
        normalized["path"] = str(cookie.get("path") or "/")
    else:
        normalized["url"] = _target_cookie_url(page_url)

    if "expirationDate" in cookie and "expires" not in cookie:
        normalized["expires"] = cookie["expirationDate"]
    if "http_only" in cookie and "httpOnly" not in cookie:
        normalized["httpOnly"] = cookie["http_only"]

    for key in ("expires", "httpOnly", "secure"):
        if key in cookie and cookie[key] is not None:
            normalized[key] = cookie[key]

    same_site = _normalize_same_site(cookie.get("sameSite") or cookie.get("same_site"))
    if same_site:
        normalized["sameSite"] = same_site

    return normalized


def _cookies_from_mapping(data, page_url):
    return [
        _normalize_cookie({"name": name, "value": value, "url": _target_cookie_url(page_url)}, page_url)
        for name, value in data.items()
    ]


def _parse_cookie_header(text, page_url):
    cookies = []
    for part in text.replace("\n", ";").split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if not name:
            continue
        cookies.append(
            {
                "name": name,
                "value": value.strip(),
                "url": _target_cookie_url(page_url),
            }
        )
    return cookies


def _parse_netscape_cookies(text):
    cookies = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        domain, _include_subdomains, path, secure, expires, name, value = parts
        cookie = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": path or "/",
            "secure": secure.upper() == "TRUE",
        }
        try:
            cookie["expires"] = int(expires)
        except ValueError:
            pass
        cookies.append(cookie)
    return cookies


def _cookie_file_ready(cookie_file):
    if not cookie_file:
        return False
    path = Path(cookie_file)
    return path.exists() and path.stat().st_size > 0


def _is_playwright_storage_state_file(cookie_file):
    if not _cookie_file_ready(cookie_file):
        return False
    try:
        data = json.loads(Path(cookie_file).read_text(encoding="utf-8"))
    except Exception:
        return False
    return (
        isinstance(data, dict)
        and isinstance(data.get("cookies"), list)
        and isinstance(data.get("origins"), list)
    )


def _save_storage_state(context, cookie_file):
    path = Path(cookie_file)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(path))
    print(f"已保存登录态：{path}")


def load_cookies_from_file(cookie_file, page_url):
    """读取已有 cookie，并转换为 Playwright ``add_cookies`` 支持的格式。

    支持 Playwright storage_state、浏览器导出的 cookie JSON、简单键值 JSON、
    ``Cookie`` 请求头字符串，以及 Netscape cookies.txt。
    """
    if not cookie_file:
        return []

    path = Path(cookie_file)
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []

    raw_cookies = []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            raw_cookies = data
        elif isinstance(data, dict) and isinstance(data.get("cookies"), list):
            raw_cookies = data["cookies"]
        elif isinstance(data, dict):
            header = data.get("cookie") or data.get("Cookie")
            if isinstance(header, str):
                raw_cookies = _parse_cookie_header(header, page_url)
            else:
                raw_cookies = _cookies_from_mapping(data, page_url)
    except json.JSONDecodeError:
        raw_cookies = _parse_netscape_cookies(text)
        if not raw_cookies:
            raw_cookies = _parse_cookie_header(text, page_url)

    cookies = []
    for cookie in raw_cookies:
        normalized = _normalize_cookie(cookie, page_url)
        if normalized:
            cookies.append(normalized)
    return cookies


def capture_api_requests(
    page_url,
    wait_seconds=8,
    interactive=True,
    cookie_file=None,
    login_url=None,
    refresh_cookie=False,
    url_filters=None,
):
    """打开目标页面并采集 XHR/Fetch 请求记录。

    默认以有头浏览器交互式采集：用户可在页面中操作触发接口，回到终端按
    Enter 结束。若 ``interactive=False``，则在页面加载后固定等待
    ``wait_seconds`` 秒。

    对 JSON 响应中的常见密文字段尝试 VIP 解密，成功时打印解密前/后各 20 个字符。

    Args:
        page_url: 待分析的页面 URL。
        wait_seconds: 非交互模式下页面加载完成后的额外等待秒数。
        interactive: 是否启用交互式采集（终端按 Enter 结束）。
        cookie_file: 可选的已有 cookie 文件路径，用于绕过登录后直接采集目标页。
        login_url: 首次登录或刷新登录态时打开的登录页；默认使用 page_url。
        refresh_cookie: 是否忽略现有 cookie 文件，重新登录并覆盖保存。
        url_filters: 可选 URL 通配符列表；设置后仅采集匹配规则的接口。

    Returns:
        接口记录列表。每条记录包含 method、url、headers、body 预览等字段。
    """
    api_records = []
    seen = set()
    capturing = True
    stop_event = threading.Event()
    normalized_url_filters = _normalize_url_filters(url_filters)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=50)

        context_options = {
            "viewport": {"width": 1366, "height": 768},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        storage_state_loaded = False
        if (
            cookie_file
            and not refresh_cookie
            and _is_playwright_storage_state_file(cookie_file)
        ):
            context_options["storage_state"] = str(Path(cookie_file))
            storage_state_loaded = True

        context = browser.new_context(**context_options)

        needs_manual_login = bool(cookie_file) and (
            refresh_cookie or not _cookie_file_ready(cookie_file)
        )

        if (
            cookie_file
            and not refresh_cookie
            and not storage_state_loaded
            and _cookie_file_ready(cookie_file)
        ):
            cookies = load_cookies_from_file(cookie_file, page_url)
            if cookies:
                context.add_cookies(cookies)
                print(f"已加载 {len(cookies)} 个 cookie：{cookie_file}")
            else:
                print(f"未从 cookie 文件读取到有效 cookie：{cookie_file}")
                needs_manual_login = True
        elif storage_state_loaded:
            print(f"已加载登录态：{cookie_file}")

        if normalized_url_filters:
            print(f"已启用接口 URL 过滤：{', '.join(normalized_url_filters)}")

        page = context.new_page()

        try:
            if needs_manual_login:
                login_page_url = login_url or page_url
                print("=" * 60)
                print("未找到可用登录态，已进入首次登录流程")
                print(f"请在浏览器中完成登录：{login_page_url}")
                print("登录成功并确认页面已进入登录后状态后，回到终端按 Enter")
                print("=" * 60)
                page.goto(login_page_url, wait_until="domcontentloaded", timeout=60000)
                input("登录完成后按 Enter 保存登录态并开始采集...")
                _save_storage_state(context, cookie_file)
        except Exception as e:
            print(f"登录态保存异常：{e}")

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

                if not url_matches_filters(request.url, normalized_url_filters):
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
