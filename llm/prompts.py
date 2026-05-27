"""LLM 提示词模板。"""

import json


def build_api_analysis_prompt(api_info):
    """构建用于接口功能分析与文档生成的用户提示词。

    Args:
        api_info: ``build_llm_input`` 返回的结构化接口信息。

    Returns:
        完整的用户消息字符串，要求模型以固定 JSON 格式输出。
    """
    return f"""
你是一名资深接口测试工程师和接口文档专家。

我会给你一个从浏览器页面中捕获到的接口结构信息。
请你根据 URL、请求方法、请求参数、请求体结构、响应体结构，推测该接口的功能，并生成可用于自动化测试的结构化接口文档信息（务必可机器执行）。

要求：
1. 不要编造接口中不存在的参数。
2. 如果某个字段含义不确定，请在描述中标明“推测”。
3. 请求参数是否必填只能根据已有信息推断，不确定时填 "unknown"。
4. 输出必须是合法 JSON，不要输出 Markdown，不要输出额外解释。
5. 字段说明要简洁、准确。
6. 如果接口功能不明显，请根据路径和字段进行合理推断。
7. confidence 表示你对接口功能推断的置信度，可选 high、medium、low。
8. 你必须输出 success_criteria 与 parameter_rules，让测试脚本可以据此生成断言与负例。
9. 任何 JSONPath/字段路径使用“点号路径”，例如：data.list[0].id（不要使用 $ 符号）。

请严格按照以下 JSON 格式输出：

{{
  "api_name": "",
  "description": "",
  "method": "",
  "path": "",
  "success_criteria": {{
    "http_status": {{
      "ok": [200],
      "retryable": [429, 503]
    }},
    "json": {{
      "must_exist_paths": [],
      "success_path": "",
      "success_values": [],
      "code_path": "",
      "ok_codes": [],
      "message_path": ""
    }}
  }},
  "parameter_rules": [
    {{
      "name": "",
      "in": "query/body/header/path",
      "type": "string/number/boolean/object/array/unknown",
      "required": "true/false/unknown",
      "enum": [],
      "min_length": null,
      "max_length": null,
      "pattern": "",
      "description": ""
    }}
  ],
  "request_params": [
    {{
      "name": "",
      "in": "query/body/header/path",
      "type": "",
      "required": "true/false/unknown",
      "description": ""
    }}
  ],
  "response_fields": [
    {{
      "name": "",
      "type": "",
      "description": ""
    }}
  ],
  "response_rules": {{
    "content_type_contains": "",
    "json_schema_hint": null,
    "must_exist_paths": []
  }},
  "possible_test_cases": [
    {{
      "case_name": "",
      "description": "",
      "expected_result": ""
    }}
  ],
  "confidence": "high/medium/low",
  "notes": []
}}

接口结构如下：

{json.dumps(api_info, ensure_ascii=False, indent=2)}
"""
