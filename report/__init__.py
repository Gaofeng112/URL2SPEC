"""报告生成：接口文档与测试报告。"""

from report.api_doc import generate_markdown_doc
from report.knowledge_base import merge_api_knowledge_base
from report.test_report import generate_markdown_report, parse_junit_xml

__all__ = [
    "generate_markdown_doc",
    "merge_api_knowledge_base",
    "generate_markdown_report",
    "parse_junit_xml",
]
