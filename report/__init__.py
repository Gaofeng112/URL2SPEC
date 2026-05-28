"""报告生成：接口文档与测试报告。"""

from report.api_doc import generate_markdown_doc
from report.knowledge_base import (
    build_api_key,
    get_known_api_keys,
    load_api_knowledge_base,
    merge_api_knowledge_base,
    knowledge_base_to_analysis_results,
)
from report.test_report import generate_markdown_report, parse_junit_xml

__all__ = [
    "generate_markdown_doc",
    "build_api_key",
    "get_known_api_keys",
    "load_api_knowledge_base",
    "merge_api_knowledge_base",
    "knowledge_base_to_analysis_results",
    "generate_markdown_report",
    "parse_junit_xml",
]
