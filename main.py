"""智能接口测试智能体入口模块。

给定页面 URL，依次完成：接口抓取、数据清洗、LLM 分析、文档生成、测试脚本生成与测试报告输出。
"""

import argparse
import json
import os
import sys

from dotenv import load_dotenv

from capture import build_llm_input, capture_api_requests
from llm import LLMClient
from report import (
    generate_markdown_doc,
    generate_markdown_report,
    merge_api_knowledge_base,
    parse_junit_xml,
)
from testing import generate_pytest_suite, run_pytest_suite

OUTPUT_DIR = "output"
DATA_DIR = f"{OUTPUT_DIR}/data"
REPORT_DIR = f"{OUTPUT_DIR}/reports"
TESTS_DIR = f"{OUTPUT_DIR}/generated_tests"
DEFAULT_KB_FILE = "docs/api_knowledge_base.json"


def get_llm_config():
    """从环境变量读取 LLM 连接配置。"""
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model = os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return api_key, base_url, model


def parse_args():
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="采集目标页接口并生成接口文档/测试脚本。")
    parser.add_argument("page_url", help="待采集的目标页面 URL")
    parser.add_argument(
        "--cookie-file",
        default=os.getenv("CAPTURE_COOKIE_FILE"),
        help="登录态文件路径；不存在时会先手动登录一次并保存，也可通过 CAPTURE_COOKIE_FILE 配置",
    )
    parser.add_argument(
        "--login-url",
        default=os.getenv("CAPTURE_LOGIN_URL"),
        help="首次登录或刷新登录态时打开的登录页；默认使用目标页面",
    )
    parser.add_argument(
        "--refresh-cookie",
        action="store_true",
        help="忽略现有登录态，重新登录并覆盖保存到 --cookie-file",
    )
    parser.add_argument(
        "--url-filter",
        action="append",
        default=_parse_csv_env("CAPTURE_URL_FILTERS"),
        help="仅采集匹配通配符的接口，可重复传入；示例：api/zgqxss/*",
    )
    parser.add_argument(
        "--kb-file",
        default=os.getenv("API_KNOWLEDGE_BASE_FILE", DEFAULT_KB_FILE),
        help=f"固定接口知识库文件路径，默认 {DEFAULT_KB_FILE}",
    )
    parser.add_argument(
        "--skip-test-filter",
        action="append",
        default=_parse_csv_env("COMMON_API_FILTERS"),
        help="匹配通配符的接口写入知识库但不生成测试，可重复传入；示例：api/common/*",
    )
    args = parser.parse_args()
    if args.refresh_cookie and not args.cookie_file:
        parser.error("--refresh-cookie 需要同时指定 --cookie-file")
    return args


def _parse_csv_env(name):
    value = os.getenv(name)
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def run_test_pipeline(analysis_results, page_url, cookie_file=None):
    """生成测试脚本、执行 pytest 并输出报告。"""
    test_cases = generate_pytest_suite(
        analysis_results,
        TESTS_DIR,
        page_url,
        cookie_file=cookie_file,
    )
    if not test_cases:
        print("未生成可执行测试（可能均为第三方埋点接口）")
        return 0

    print(f"已生成 {len(test_cases)} 条接口测试：{TESTS_DIR}/test_generated_api.py")

    exit_code, junit_path, stdout, stderr = run_pytest_suite(TESTS_DIR, REPORT_DIR)
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)

    result = parse_junit_xml(junit_path)
    generate_markdown_report(result, f"{REPORT_DIR}/test_report.md", test_cases=test_cases)

    summary = (result or {}).get("summary", {})
    print(
        f"测试完成：通过 {summary.get('passed', 0)}/"
        f"{summary.get('tests', 0)}，退出码 {exit_code}"
    )
    return exit_code


def main():
    """执行完整的接口采集、分析与测试流水线。"""
    load_dotenv()
    args = parse_args()
    page_url = args.page_url
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)

    raw_records = capture_api_requests(
        page_url,
        cookie_file=args.cookie_file,
        login_url=args.login_url,
        refresh_cookie=args.refresh_cookie,
        url_filters=args.url_filter,
    )
    with open(f"{DATA_DIR}/api_records_raw.json", "w", encoding="utf-8") as f:
        json.dump(raw_records, f, ensure_ascii=False, indent=2)

    llm_inputs = [build_llm_input(record) for record in raw_records]
    with open(f"{DATA_DIR}/api_records_clean.json", "w", encoding="utf-8") as f:
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

    with open(f"{DATA_DIR}/api_analysis.json", "w", encoding="utf-8") as f:
        json.dump(analysis_results, f, ensure_ascii=False, indent=2)

    kb_results = merge_api_knowledge_base(
        analysis_results,
        args.kb_file,
        skip_test_filters=args.skip_test_filter,
    )
    with open(f"{DATA_DIR}/api_knowledge_base_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(kb_results, f, ensure_ascii=False, indent=2)
    print(f"接口知识库已更新：{args.kb_file}")

    markdown = generate_markdown_doc(kb_results)
    with open(f"{REPORT_DIR}/api_doc.md", "w", encoding="utf-8") as f:
        f.write(markdown)

    run_test_pipeline(kb_results, page_url, cookie_file=args.cookie_file)

    print("处理完成")
    print(f"原始抓包数据：{DATA_DIR}/api_records_raw.json")
    print(f"清洗后数据：{DATA_DIR}/api_records_clean.json")
    print(f"LLM 分析结果：{DATA_DIR}/api_analysis.json")
    print(f"接口知识库：{args.kb_file}")
    print(f"接口文档：{REPORT_DIR}/api_doc.md")
    print(f"测试脚本：{TESTS_DIR}/test_generated_api.py")
    print(f"测试报告：{REPORT_DIR}/test_report.md")


if __name__ == "__main__":
    main()
