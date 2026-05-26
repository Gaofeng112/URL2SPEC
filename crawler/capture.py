"""使用 Playwright 打开页面并捕获 XHR/Fetch 网络请求。"""

import base64
import hashlib
from datetime import datetime
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from utils.sanitizer import safe_preview_body, sanitize_headers
# 按 URL 路径后缀识别的静态资源扩展名，用于过滤非业务接口。
STATIC_EXTENSIONS = (
    ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".map", ".webp", ".mp4", ".mp3",
)


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


def capture_api_requests(page_url, wait_seconds=8):
    """打开目标页面并采集所有 XHR/Fetch 请求记录。

    使用 Chromium 有头模式访问页面，在 ``domcontentloaded`` 后再等待
    ``wait_seconds`` 秒，以便 SPA 触发异步接口。

    Args:
        page_url: 待分析的页面 URL。
        wait_seconds: 页面加载完成后额外等待的秒数，用于捕获延迟发起的请求。

    Returns:
        接口记录列表。每条记录包含 method、url、headers、body 预览等字段。
    """
    api_records = []
    seen = set()
    capturing = True

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=100)

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
                }

                try:
                    if "application/json" in content_type:
                        body = response.json()
                        record["response_body_preview"] = safe_preview_body(body)
                    elif "text" in content_type or "html" in content_type:
                        text = response.text()
                        record["response_body_preview"] = text[:1000]
                    else:
                        record["response_body_preview"] = "[非文本响应，已忽略]"
                except Exception as e:
                    record["response_body_preview"] = f"[响应体读取失败：{str(e)}]"

                api_records.append(record)
                print(f"[接口] {request.method} {request.url} {response.status}")
            except Exception as e:
                print(f"[警告] 跳过无法处理的响应：{e}")

        page.on("response", handle_response)

        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(wait_seconds * 1000)
        except Exception as e:
            print(f"页面访问异常：{e}")
        finally:
            capturing = False
            page.wait_for_timeout(500)
            browser.close()

    return api_records
