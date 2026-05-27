"""报告生成模块单元测试。"""

from report.test_report import generate_markdown_report, parse_junit_xml


def test_parse_junit_xml(tmp_path):
    """解析最小 JUnit XML 样例。"""
    xml = tmp_path / "results.xml"
    xml.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1" failures="0" errors="0" skipped="0" time="0.1">
  <testcase classname="test" name="test_ok" time="0.1"/>
</testsuite>
""",
        encoding="utf-8",
    )
    result = parse_junit_xml(xml)
    assert result["summary"]["tests"] == 1
    assert result["summary"]["passed"] == 1
    assert result["cases"][0]["status"] == "passed"


def test_generate_markdown_report(tmp_path):
    """生成 Markdown 报告文件。"""
    result = {
        "summary": {
            "tests": 1,
            "passed": 1,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "time": 0.2,
        },
        "cases": [{"name": "test_ok", "status": "passed", "time": 0.2, "message": ""}],
    }
    out = tmp_path / "report.md"
    generate_markdown_report(result, out)
    assert "接口测试报告" in out.read_text(encoding="utf-8")
