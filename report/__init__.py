"""报告生成：接口文档与测试报告。"""

from report.api_doc import generate_markdown_doc
from report.test_report import generate_markdown_report, parse_junit_xml

__all__ = ["generate_markdown_doc", "generate_markdown_report", "parse_junit_xml"]
