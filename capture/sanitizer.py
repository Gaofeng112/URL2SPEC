"""敏感信息脱敏与响应体截断。"""

# 命中后将值替换为 "***" 的请求/响应头名称（小写比较）。
SENSITIVE_HEADERS = {
    "cookie",
    "authorization",
    "proxy-authorization",
    "x-token",
    "token",
    "set-cookie",
}


def sanitize_headers(headers):
    """对 HTTP 头中的敏感字段进行脱敏。

    Args:
        headers: 原始请求或响应头字典。

    Returns:
        脱敏后的新字典，敏感字段值统一为 ``"***"``。
    """
    safe_headers = {}

    for key, value in headers.items():
        if key.lower() in SENSITIVE_HEADERS:
            safe_headers[key] = "***"
        else:
            safe_headers[key] = value

    return safe_headers


def safe_preview_body(body, max_length=2000):
    """截断响应体预览，避免持久化过多第三方数据。

    Args:
        body: 响应体内容，通常为 dict/list 或字符串。
        max_length: 字符串形式下的最大保留长度。

    Returns:
        未超长时返回原 ``body``；超长时返回截断后的字符串。
    """
    text = str(body)

    if len(text) > max_length:
        return text[:max_length] + "...[内容过长，已截断]"

    return body
