"""OpenAI 兼容接口的 LLM 客户端封装。"""

import json
import re

from openai import OpenAI

from llm.prompts import build_api_analysis_prompt


def parse_llm_json(content):
    """解析 LLM 返回内容为 JSON 对象。

    支持去除 Markdown 代码块包裹（`` ```json ... ``` ``）。

    Args:
        content: LLM 原始文本输出。

    Returns:
        解析后的 Python 字典或列表。

    Raises:
        json.JSONDecodeError: 内容不是合法 JSON 时抛出。
    """
    text = content.strip()

    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fenced:
        text = fenced.group(1).strip()

    return json.loads(text)


class LLMClient:
    """调用大模型分析接口结构并生成文档字段。"""

    def __init__(self, api_key, base_url=None, model="gpt-4o-mini"):
        """初始化 OpenAI 兼容客户端。

        Args:
            api_key: API 密钥。
            base_url: 可选的自定义 API 基地址（代理或私有部署）。
            model: 模型名称，默认 ``gpt-4o-mini``。
        """
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def analyze_api(self, api_info):
        """分析单条接口并返回结构化文档字段。

        Args:
            api_info: ``build_llm_input`` 生成的字典。

        Returns:
            解析成功的 LLM JSON 结果；若解析失败则返回包含
            ``api_name="解析失败"`` 与 ``raw_output`` 的兜底字典。
        """
        prompt = build_api_analysis_prompt(api_info)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一个专业的接口文档生成与接口测试规则抽取助手。"
                        "你只能输出合法 JSON（不要 Markdown/解释文本）。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )

        content = response.choices[0].message.content.strip()

        try:
            return parse_llm_json(content)
        except (json.JSONDecodeError, TypeError):
            return {
                "api_name": "解析失败",
                "description": "LLM 返回结果不是合法 JSON",
                "raw_output": content,
                "confidence": "low",
                "notes": ["需要人工检查 LLM 输出"],
            }
