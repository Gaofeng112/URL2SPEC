"""URL 与查询参数的解析工具。"""

from urllib.parse import parse_qs, urlparse


def parse_url_info(url):
    """解析 URL 中的域名、路径与查询参数。

    Args:
        url: 完整请求 URL。

    Returns:
        字典，包含 ``domain``、``path``、``query_params`` 三个键。
        ``query_params`` 的值为推断出的 JSON Schema 类型字符串。
    """
    parsed = urlparse(url)
    query_params = {}
    raw_query = parse_qs(parsed.query)

    for key, values in raw_query.items():
        if not values:
            query_params[key] = "unknown"
        else:
            query_params[key] = guess_value_type(values[0])

    return {
        "domain": parsed.netloc,
        "path": parsed.path,
        "query_params": query_params,
    }


def guess_value_type(value):
    """根据字符串内容推测查询参数值的 JSON Schema 类型。

    Args:
        value: 查询参数的单值（字符串或 ``None``）。

    Returns:
        类型名称：``"null"``、``"number"``、``"boolean"`` 或 ``"string"``。
    """
    if value is None:
        return "null"

    value = str(value)

    if value.isdigit():
        return "number"

    if value.lower() in ("true", "false"):
        return "boolean"

    return "string"
