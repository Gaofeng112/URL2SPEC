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


def test_generate_markdown_report_with_api_details(tmp_path):
    """测试报告应包含接口地址、请求参数和响应参数。"""
    result = {
        "summary": {
            "tests": 1,
            "passed": 1,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "time": 0.2,
        },
        "cases": [{"name": "test_1_GET_api_user_ok", "status": "passed", "time": 0.2, "message": ""}],
    }
    test_cases = [{
        "func_name": "1_GET_api_user",
        "api_name": "用户信息",
        "method": "GET",
        "url": "https://example.com/api/user",
        "request_params": [{
            "name": "id",
            "in": "query",
            "type": "string",
            "required": "true",
            "description": "用户 ID",
        }],
        "response_fields": [{
            "name": "data.name",
            "type": "string",
            "description": "用户名",
        }],
    }]
    out = tmp_path / "report.md"

    generate_markdown_report(result, out, test_cases=test_cases)
    text = out.read_text(encoding="utf-8")

    assert "https://example.com/api/user" in text
    assert "用户 ID" in text
    assert "data.name" in text
