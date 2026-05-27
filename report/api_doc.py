"""将 LLM 分析结果渲染为 Markdown 接口文档。"""


def generate_markdown_doc(analysis_results):
    """生成完整的 Markdown 接口文档。

    Args:
        analysis_results: 列表，每项包含 ``source``（清洗后抓包数据）
            与 ``analysis``（LLM 分析结果）两个键。

    Returns:
        Markdown 格式的文档字符串。
    """
    md = "# 接口文档\n\n"
    md += (
        "> 本文档由接口采集工具结合 LLM 自动生成，"
        "接口功能和字段含义为模型推测结果，建议人工复核。\n\n"
    )

    for index, item in enumerate(analysis_results, start=1):
        source = item.get("source", {})
        analysis = item.get("analysis", {})

        md += "---\n\n"
        md += f"## {index}. {analysis.get('api_name', '未命名接口')}\n\n"
        md += f"**请求方法：** `{analysis.get('method') or source.get('method')}`\n\n"
        md += f"**接口路径：** `{analysis.get('path') or source.get('path')}`\n\n"
        md += f"**接口域名：** `{source.get('domain')}`\n\n"
        md += f"**接口说明：** {analysis.get('description', '')}\n\n"
        md += f"**置信度：** `{analysis.get('confidence', 'unknown')}`\n\n"

        md += _render_params_table(analysis.get("request_params", []))
        md += _render_fields_table(analysis.get("response_fields", []))
        md += _render_test_cases_table(analysis.get("possible_test_cases", []))
        md += _render_notes(analysis.get("notes", []))
        md += "\n"

    return md


def _render_params_table(params):
    """渲染请求参数 Markdown 表格。

    Args:
        params: ``request_params`` 列表。

    Returns:
        包含三级标题与表格的 Markdown 片段。
    """
    md = "### 请求参数\n\n"
    if not params:
        return md + "无\n\n"

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
    return md + "\n"


def _render_fields_table(fields):
    """渲染响应字段 Markdown 表格。

    Args:
        fields: ``response_fields`` 列表。

    Returns:
        包含三级标题与表格的 Markdown 片段。
    """
    md = "### 响应字段\n\n"
    if not fields:
        return md + "无\n\n"

    md += "| 字段名 | 类型 | 说明 |\n"
    md += "|---|---|---|\n"
    for field in fields:
        md += (
            f"| {field.get('name', '')} "
            f"| {field.get('type', '')} "
            f"| {field.get('description', '')} |\n"
        )
    return md + "\n"


def _render_test_cases_table(cases):
    """渲染测试用例 Markdown 表格。

    Args:
        cases: ``possible_test_cases`` 列表。

    Returns:
        包含三级标题与表格的 Markdown 片段。
    """
    md = "### 可能的测试用例\n\n"
    if not cases:
        return md + "暂无\n\n"

    md += "| 用例名称 | 描述 | 预期结果 |\n"
    md += "|---|---|---|\n"
    for case in cases:
        md += (
            f"| {case.get('case_name', '')} "
            f"| {case.get('description', '')} "
            f"| {case.get('expected_result', '')} |\n"
        )
    return md + "\n"


def _render_notes(notes):
    """渲染备注列表。

    Args:
        notes: 字符串备注列表。

    Returns:
        包含三级标题与列表项的 Markdown 片段。
    """
    md = "### 备注\n\n"
    if not notes:
        return md + "- 无\n\n"

    for note in notes:
        md += f"- {note}\n"
    return md + "\n"
