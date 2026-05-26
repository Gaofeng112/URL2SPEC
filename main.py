"""智能接口测试智能体入口模块。

给定页面 URL，依次完成：接口抓取、数据清洗、LLM 分析、文档生成、测试脚本生成与测试报告输出。
"""

import json
import os
import sys

from dotenv import load_dotenv

from crawler.capture import capture_api_requests
from generator.markdown_generator import generate_markdown_doc
from generator.report_generator import (
    generate_html_report,
    generate_json_report,
    generate_markdown_report,
    parse_junit_xml,
)
from generator.test_script_generator import generate_pytest_suite
from llm.llm_client import LLMClient
from processor.cleaner import build_llm_input
from runner.test_runner import run_pytest_suite

OUTPUT_DIR = "output"
TESTS_DIR = f"{OUTPUT_DIR}/tests"


def get_llm_config():
    """从环境变量读取 LLM 连接配置。

    同时支持 ``LLM_*`` 与 ``OPENAI_*`` 两套变量名，便于兼容不同部署习惯。

    Returns:
        三元组 ``(api_key, base_url, model)``。``api_key`` 未配置时为 ``None``。
    """
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model = os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return api_key, base_url, model


def run_test_pipeline(analysis_results, page_url):
    """生成测试脚本、执行 pytest 并输出报告。

    Args:
        analysis_results: 含 ``raw``、``source``、``analysis`` 的列表。
        page_url: 用户输入的页面 URL。

    Returns:
        pytest 退出码。
    """
    test_cases = generate_pytest_suite(analysis_results, TESTS_DIR, page_url)
    if not test_cases:
        print("未生成可执行测试（可能均为第三方埋点接口）")
        return 0

    print(f"已生成 {len(test_cases)} 条接口测试：{TESTS_DIR}/test_generated_api.py")

    exit_code, junit_path, stdout, stderr = run_pytest_suite(TESTS_DIR, OUTPUT_DIR)
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)

    result = parse_junit_xml(junit_path)
    generate_json_report(result, f"{OUTPUT_DIR}/test_report.json")
    generate_markdown_report(result, f"{OUTPUT_DIR}/test_report.md")
    generate_html_report(result, f"{OUTPUT_DIR}/test_report.html")

    summary = (result or {}).get("summary", {})
    print(
        f"测试完成：通过 {summary.get('passed', 0)}/"
        f"{summary.get('tests', 0)}，退出码 {exit_code}"
    )
    return exit_code


def main():
    """执行完整的接口采集、分析与测试流水线。"""
    load_dotenv()

    if len(sys.argv) < 2:
        print('用法：python main.py "https://www.yaozh.com/"')
        return

    page_url = sys.argv[1]
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    raw_records = capture_api_requests(page_url)
    with open(f"{OUTPUT_DIR}/api_records_raw.json", "w", encoding="utf-8") as f:
        json.dump(raw_records, f, ensure_ascii=False, indent=2)

    llm_inputs = [build_llm_input(record) for record in raw_records]
    with open(f"{OUTPUT_DIR}/api_records_clean.json", "w", encoding="utf-8") as f:
        json.dump(llm_inputs, f, ensure_ascii=False, indent=2)

    api_key, base_url, model = get_llm_config()
    if not api_key:
        print("未配置 LLM_API_KEY 或 OPENAI_API_KEY，无法调用大模型")
        return

    if not llm_inputs:
        print("未捕获到任何 XHR/Fetch 接口，请检查目标页面或延长等待时间")
        return

    llm_client = LLMClient(api_key=api_key, base_url=base_url, model=model)
    analysis_results = []

    for index, api_info in enumerate(llm_inputs, start=1):
        print(
            f"正在分析第 {index}/{len(llm_inputs)} 个接口："
            f"{api_info['method']} {api_info['path']}"
        )
        result = llm_client.analyze_api(api_info)
        analysis_results.append({
            "raw": raw_records[index - 1],
            "source": api_info,
            "analysis": result,
        })

    with open(f"{OUTPUT_DIR}/api_analysis.json", "w", encoding="utf-8") as f:
        json.dump(analysis_results, f, ensure_ascii=False, indent=2)

    markdown = generate_markdown_doc(analysis_results)
    with open(f"{OUTPUT_DIR}/api_doc.md", "w", encoding="utf-8") as f:
        f.write(markdown)

    run_test_pipeline(analysis_results, page_url)

    print("处理完成")
    print(f"原始抓包数据：{OUTPUT_DIR}/api_records_raw.json")
    print(f"清洗后数据：{OUTPUT_DIR}/api_records_clean.json")
    print(f"LLM 分析结果：{OUTPUT_DIR}/api_analysis.json")
    print(f"接口文档：{OUTPUT_DIR}/api_doc.md")
    print(f"测试脚本：{TESTS_DIR}/test_generated_api.py")
    print(f"测试报告：{OUTPUT_DIR}/test_report.html")


if __name__ == "__main__":
    main()
