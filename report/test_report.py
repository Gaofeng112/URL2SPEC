"""根据 pytest JUnit XML 生成测试报告（JSON / Markdown / HTML）。"""

import json
import xml.etree.ElementTree as ET
from datetime import datetime
from html import escape
from pathlib import Path


def parse_junit_xml(junit_path):
    """解析 pytest 输出的 JUnit XML。

    Args:
        junit_path: XML 文件路径。

    Returns:
        包含 summary 与 cases 列表的字典；文件不存在时返回 ``None``。
    """
    path = Path(junit_path)
    if not path.is_file():
        return None

    root = ET.parse(path).getroot()
    if root.tag == "testsuites":
        suite = root.find("testsuite")
    else:
        suite = root

    if suite is None:
        return None

    summary = {
        "tests": int(suite.attrib.get("tests", 0)),
        "failures": int(suite.attrib.get("failures", 0)),
        "errors": int(suite.attrib.get("errors", 0)),
        "skipped": int(suite.attrib.get("skipped", 0)),
        "time": float(suite.attrib.get("time", 0)),
    }
    summary["passed"] = (
        summary["tests"] - summary["failures"] - summary["errors"] - summary["skipped"]
    )

    cases = []
    for case in suite.findall("testcase"):
        name = case.attrib.get("name", "")
        classname = case.attrib.get("classname", "")
        time_spent = float(case.attrib.get("time", 0))

        status = "passed"
        message = ""
        detail = ""

        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")

        if failure is not None:
            status = "failed"
            message = failure.attrib.get("message", "")
            detail = failure.text or ""
        elif error is not None:
            status = "error"
            message = error.attrib.get("message", "")
            detail = error.text or ""
        elif skipped is not None:
            status = "skipped"
            message = skipped.attrib.get("message", "")

        cases.append({
            "name": name,
            "classname": classname,
            "status": status,
            "time": time_spent,
            "message": message.strip(),
            "detail": detail.strip(),
        })

    return {"summary": summary, "cases": cases}


def generate_json_report(result, output_path):
    """写入 JSON 格式测试报告。

    Args:
        result: ``parse_junit_xml`` 的返回值。
        output_path: 输出文件路径。

    Returns:
        写入的绝对路径字符串。
    """
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **(result or {"summary": {}, "cases": []}),
    }
    path = Path(output_path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def enrich_report_with_api_details(result, test_cases):
    """将测试用例元数据挂到 JUnit 解析结果中。"""
    if not result:
        return result

    case_map = {}
    for case in test_cases or []:
        func_name = case.get("func_name")
        if not func_name:
            continue
        detail = {
            "api_name": case.get("api_name", ""),
            "method": case.get("method", ""),
            "url": case.get("url", ""),
            "request_params": case.get("request_params") or case.get("parameter_rules") or [],
            "parameter_rules": case.get("parameter_rules") or [],
            "request_body": case.get("request_body"),
            "response_fields": case.get("response_fields") or [],
            "response_rules": case.get("response_rules") or {},
        }
        case_map[f"test_{func_name}_ok"] = detail
        case_map[f"test_{func_name}_missing_required_param"] = detail

    for case in result.get("cases", []):
        detail = case_map.get(case.get("name", ""))
        if detail:
            case["api"] = detail
    return result


def generate_markdown_report(result, output_path, test_cases=None):
    """写入 Markdown 格式测试报告。

    Args:
        result: ``parse_junit_xml`` 的返回值。
        output_path: 输出文件路径。

    Returns:
        写入的绝对路径字符串。
    """
    result = enrich_report_with_api_details(
        result or {"summary": {}, "cases": []},
        test_cases,
    )
    summary = result.get("summary", {})
    cases = result.get("cases", [])

    md = "# 接口测试报告\n\n"
    md += f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    md += "## 汇总\n\n"
    md += f"- 总计：{summary.get('tests', 0)}\n"
    md += f"- 通过：{summary.get('passed', 0)}\n"
    md += f"- 失败：{summary.get('failures', 0)}\n"
    md += f"- 错误：{summary.get('errors', 0)}\n"
    md += f"- 跳过：{summary.get('skipped', 0)}\n"
    md += f"- 耗时：{summary.get('time', 0):.2f}s\n\n"

    md += "## 用例明细\n\n"
    md += "| 用例 | 状态 | 耗时(s) | 说明 |\n"
    md += "|---|---|---|---|\n"

    for case in cases:
        msg = (case.get("message") or "").replace("|", "\\|").replace("\n", " ")
        md += (
            f"| `{case.get('name', '')}` "
            f"| {case.get('status', '')} "
            f"| {case.get('time', 0):.2f} "
            f"| {msg or '-'} |\n"
        )

    md += "\n## 接口明细\n\n"
    for index, case in enumerate(cases, start=1):
        api = case.get("api") or {}
        md += f"### {index}. `{case.get('name', '')}`\n\n"
        md += f"- 状态：{case.get('status', '')}\n"
        md += f"- 接口名称：{api.get('api_name') or '-'}\n"
        md += f"- 请求方法：`{api.get('method') or '-'}`\n"
        md += f"- 接口地址：`{api.get('url') or '-'}`\n\n"
        md += _render_request_params(api)
        md += _render_response_params(api)
        if case.get("message"):
            md += f"**失败/跳过说明：** {case.get('message')}\n\n"
        if case.get("detail") and case.get("status") in ("failed", "error"):
            detail = case.get("detail")
            if len(detail) > 1200:
                detail = detail[:1200] + "\n..."
            md += f"失败详情：\n\n```text\n{detail}\n```\n\n"

    path = Path(output_path)
    path.write_text(md, encoding="utf-8")
    return str(path)


def _render_request_params(api):
    params = api.get("request_params") or api.get("parameter_rules") or []
    body = api.get("request_body")
    md = "**请求参数：**\n\n"
    if params:
        md += "| 参数名 | 位置 | 类型 | 是否必填 | 说明 |\n"
        md += "|---|---|---|---|---|\n"
        for param in params:
            md += (
                f"| {param.get('name', '')} "
                f"| {param.get('in', '')} "
                f"| {param.get('type', '')} "
                f"| {param.get('required', '')} "
                f"| {param.get('description', '')} |\n"
            )
        md += "\n"
    else:
        md += "无结构化请求参数\n\n"

    if body:
        preview = str(body)
        if len(preview) > 500:
            preview = preview[:500] + "..."
        md += f"请求体样例：\n\n```text\n{preview}\n```\n\n"
    return md


def _render_response_params(api):
    fields = api.get("response_fields") or []
    rules = api.get("response_rules") or {}
    md = "**响应参数：**\n\n"
    if fields:
        md += "| 字段名 | 类型 | 说明 |\n"
        md += "|---|---|---|\n"
        for field in fields:
            md += (
                f"| {field.get('name', '')} "
                f"| {field.get('type', '')} "
                f"| {field.get('description', '')} |\n"
            )
        md += "\n"
    else:
        paths = rules.get("must_exist_paths") or []
        if paths:
            md += "必须存在字段路径：\n\n"
            for path in paths:
                md += f"- `{path}`\n"
            md += "\n"
        else:
            md += "无结构化响应参数\n\n"
    return md


def generate_html_report(result, output_path):
    """写入 HTML 格式测试报告。

    Args:
        result: ``parse_junit_xml`` 的返回值。
        output_path: 输出文件路径。

    Returns:
        写入的绝对路径字符串。
    """
    result = result or {"summary": {}, "cases": []}
    summary = result.get("summary", {})
    cases = result.get("cases", [])

    rows = []
    for case in cases:
        status = case.get("status", "")
        badge_class = {
            "passed": "pass",
            "failed": "fail",
            "error": "fail",
            "skipped": "skip",
        }.get(status, "")
        rows.append(
            f"<tr class='{badge_class}'>"
            f"<td>{escape(case.get('name', ''))}</td>"
            f"<td>{escape(status)}</td>"
            f"<td>{case.get('time', 0):.2f}</td>"
            f"<td><pre>{escape(case.get('message') or '-')}</pre></td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <title>接口测试报告</title>
  <style>
    body {{ font-family: sans-serif; margin: 24px; }}
    .summary span {{ margin-right: 16px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    tr.pass td:nth-child(2) {{ color: #0a0; }}
    tr.fail td:nth-child(2) {{ color: #c00; }}
    tr.skip td:nth-child(2) {{ color: #888; }}
    pre {{ white-space: pre-wrap; margin: 0; }}
  </style>
</head>
<body>
  <h1>接口测试报告</h1>
  <p>生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
  <div class="summary">
    <span>总计：<b>{summary.get('tests', 0)}</b></span>
    <span>通过：<b>{summary.get('passed', 0)}</b></span>
    <span>失败：<b>{summary.get('failures', 0)}</b></span>
    <span>错误：<b>{summary.get('errors', 0)}</b></span>
    <span>跳过：<b>{summary.get('skipped', 0)}</b></span>
    <span>耗时：<b>{summary.get('time', 0):.2f}s</b></span>
  </div>
  <table>
    <thead>
      <tr><th>用例</th><th>状态</th><th>耗时(s)</th><th>说明</th></tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
    path = Path(output_path)
    path.write_text(html, encoding="utf-8")
    return str(path)
