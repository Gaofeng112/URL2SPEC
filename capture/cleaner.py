"""将原始抓包记录转换为 LLM 可消费的结构化输入。"""

import json

from capture.parsers import parse_url_info
from capture.schema_infer import infer_schema

# 非 JSON 请求/响应体在送入 LLM 前的最大字符数。
_BODY_TEXT_LIMIT = 500


def build_llm_input(record):
    """从单条抓包记录构建 LLM 分析所需的精简结构。

    Args:
        record: ``capture_api_requests`` 返回的单条字典，需包含 ``url``、
            ``method``、``status`` 等字段。

    Returns:
        包含 method、domain、path、query_params、request_body_schema、
        response_body_schema 等键的字典。
    """
    url_info = parse_url_info(record["url"])

    response_body = record.get("response_body_preview")
    if isinstance(response_body, (dict, list)):
        response_schema = infer_schema(response_body)
    else:
        response_schema = (
            str(response_body)[:_BODY_TEXT_LIMIT] if response_body else None
        )

    request_body = record.get("request_body")
    request_body_schema = None
    if request_body:
        try:
            request_json = json.loads(request_body)
            request_body_schema = infer_schema(request_json)
        except json.JSONDecodeError:
            request_body_schema = str(request_body)[:_BODY_TEXT_LIMIT]

    return {
        "method": record.get("method"),
        "domain": url_info["domain"],
        "path": url_info["path"],
        "query_params": url_info["query_params"],
        "request_body_schema": request_body_schema,
        "response_status": record.get("status"),
        "response_content_type": record.get("content_type"),
        "response_body_schema": response_schema,
    }
