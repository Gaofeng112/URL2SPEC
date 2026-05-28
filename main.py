"""智能接口测试智能体入口模块。

给定页面 URL，依次完成：接口抓取、数据清洗、LLM 分析、文档生成、测试脚本生成与测试报告输出。
"""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from capture import build_llm_input, capture_api_requests
from llm import LLMClient
from report import (
    build_api_key,
    generate_markdown_doc,
    generate_markdown_report,
    get_known_api_keys,
    merge_api_knowledge_base,
    parse_junit_xml,
)
from testing import generate_pytest_suite, run_pytest_suite

OUTPUT_DIR = Path("output")
DATA_DIR = OUTPUT_DIR / "data"
RUN_REPORT_DIR = OUTPUT_DIR / "reports"
TESTS_DIR = OUTPUT_DIR / "generated_tests"
CONFIG_DIR = Path("config")
DOCS_DIR = Path("docs")
API_DOC_PATH = DOCS_DIR / "api_doc.md"
TEST_REPORT_PATH = DOCS_DIR / "test_report.md"
DEFAULT_KB_FILE = DOCS_DIR / "api_knowledge_base.json"


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
        help="登录态文件路径；默认按目标域名保存到 config/，也可通过 CAPTURE_COOKIE_FILE 配置",
    )
    parser.add_argument(
        "--login-url",
        default=os.getenv("CAPTURE_LOGIN_URL"),
        help="首次登录或刷新登录态时打开的登录页；默认使用目标页面",
    )
    parser.add_argument(
        "--refresh-cookie",
        action="store_true",
        help="忽略现有登录态，重新登录并覆盖保存到当前登录态文件",
    )
    parser.add_argument(
        "--url-filter",
        action="append",
        default=_parse_csv_env("CAPTURE_URL_FILTERS"),
        help="仅采集匹配通配符的接口，可重复传入；示例：api/zgqxss/*",
    )
    parser.add_argument(
        "--kb-file",
        default=os.getenv("API_KNOWLEDGE_BASE_FILE", str(DEFAULT_KB_FILE)),
        help=f"固定接口知识库文件路径，默认 {DEFAULT_KB_FILE}",
    )
    parser.add_argument(
        "--skip-test-filter",
        action="append",
        default=_parse_csv_env("COMMON_API_FILTERS"),
        help="匹配通配符的接口写入知识库但不生成测试，可重复传入；示例：api/common/*",
    )
    parser.add_argument(
        "--rebuild-kb",
        action="store_true",
        help="忽略已有知识库，本次抓到的接口全部重新分析，并覆盖写入知识库后再测试",
    )
    args = parser.parse_args()
    if not args.cookie_file:
        args.cookie_file = default_cookie_file_for_url(args.page_url)
    return args


def default_cookie_file_for_url(page_url):
    """按目标站点生成默认登录态文件，避免每次命令都传 --cookie-file。"""
    parsed = urlparse(page_url)
    site = parsed.hostname or parsed.netloc or parsed.path
    try:
        if parsed.port:
            site = f"{site}_{parsed.port}"
    except ValueError:
        pass
    safe_site = "".join(ch if ch.isalnum() or ch in ".-" else "_" for ch in site).strip("._-")
    if not safe_site:
        safe_site = "default"
    return str(CONFIG_DIR / f"{safe_site}.storage_state.json")


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

    print(f"已生成 {len(test_cases)} 条接口测试：{TESTS_DIR / 'test_generated_api.py'}")

    exit_code, junit_path, stdout, stderr = run_pytest_suite(TESTS_DIR, RUN_REPORT_DIR)
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)

    result = parse_junit_xml(junit_path)
    generate_markdown_report(result, TEST_REPORT_PATH, test_cases=test_cases)

    summary = (result or {}).get("summary", {})
    print(
        f"测试完成：通过 {summary.get('passed', 0)}/"
        f"{summary.get('tests', 0)}，退出码 {exit_code}"
    )
    return exit_code


def split_new_api_records(raw_records, llm_inputs, kb_file):
    """按知识库过滤已处理接口，仅返回需要 LLM 分析的新接口。"""
    known_keys = get_known_api_keys(kb_file)
    new_records = []
    new_inputs = []
    skipped = []

    for raw_record, api_info in zip(raw_records, llm_inputs):
        key = build_api_key(api_info)
        if key in known_keys:
            skipped.append(api_info)
            continue
        new_records.append(raw_record)
        new_inputs.append(api_info)

    return new_records, new_inputs, skipped


def main():
    """执行完整的接口采集、分析与测试流水线。"""
    load_dotenv()
    args = parse_args()
    page_url = args.page_url
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(RUN_REPORT_DIR, exist_ok=True)
    os.makedirs(DOCS_DIR, exist_ok=True)

    raw_records = capture_api_requests(
        page_url,
        cookie_file=args.cookie_file,
        login_url=args.login_url,
        refresh_cookie=args.refresh_cookie,
        url_filters=args.url_filter,
    )
    with open(DATA_DIR / "api_records_raw.json", "w", encoding="utf-8") as f:
        json.dump(raw_records, f, ensure_ascii=False, indent=2)

    llm_inputs = [build_llm_input(record) for record in raw_records]
    with open(DATA_DIR / "api_records_clean.json", "w", encoding="utf-8") as f:
        json.dump(llm_inputs, f, ensure_ascii=False, indent=2)

    if args.rebuild_kb:
        new_raw_records, new_llm_inputs, skipped_known = raw_records, llm_inputs, []
        print("已启用知识库重建：忽略已有知识库，本次接口将全部重新分析并覆盖保存")
    else:
        new_raw_records, new_llm_inputs, skipped_known = split_new_api_records(
            raw_records,
            llm_inputs,
            args.kb_file,
        )
        if skipped_known:
            print(f"已跳过 {len(skipped_known)} 个知识库已有接口，避免重复 LLM 分析")

    if not new_llm_inputs:
        if not llm_inputs:
            print("未捕获到任何 XHR/Fetch 接口，请检查目标页面或延长等待时间")
            return
        print("本次未发现新增接口，直接使用现有知识库生成文档和测试")
        kb_results = merge_api_knowledge_base(
            [],
            args.kb_file,
            skip_test_filters=args.skip_test_filter,
        )
        markdown = generate_markdown_doc(kb_results)
        with open(API_DOC_PATH, "w", encoding="utf-8") as f:
            f.write(markdown)
        run_test_pipeline(kb_results, page_url, cookie_file=args.cookie_file)
        return

    api_key, base_url, model = get_llm_config()
    if not api_key:
        print("未配置 LLM_API_KEY 或 OPENAI_API_KEY，无法调用大模型")
        return

    llm_client = LLMClient(api_key=api_key, base_url=base_url, model=model)
    analysis_results = []

    for index, api_info in enumerate(new_llm_inputs, start=1):
        print(
            f"正在分析新增接口第 {index}/{len(new_llm_inputs)} 个："
            f"{api_info['method']} {api_info['path']}"
        )
        result = llm_client.analyze_api(api_info)
        analysis_results.append({
            "raw": new_raw_records[index - 1],
            "source": api_info,
            "analysis": result,
        })

    with open(DATA_DIR / "api_analysis.json", "w", encoding="utf-8") as f:
        json.dump(analysis_results, f, ensure_ascii=False, indent=2)

    kb_results = merge_api_knowledge_base(
        analysis_results,
        args.kb_file,
        skip_test_filters=args.skip_test_filter,
        overwrite=args.rebuild_kb,
    )
    with open(DATA_DIR / "api_knowledge_base_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(kb_results, f, ensure_ascii=False, indent=2)
    print(f"接口知识库已更新：{args.kb_file}")

    markdown = generate_markdown_doc(kb_results)
    with open(API_DOC_PATH, "w", encoding="utf-8") as f:
        f.write(markdown)

    run_test_pipeline(kb_results, page_url, cookie_file=args.cookie_file)

    print("处理完成")
    print(f"原始抓包数据：{DATA_DIR / 'api_records_raw.json'}")
    print(f"清洗后数据：{DATA_DIR / 'api_records_clean.json'}")
    print(f"LLM 分析结果：{DATA_DIR / 'api_analysis.json'}")
    print(f"接口知识库：{args.kb_file}")
    print(f"接口文档：{API_DOC_PATH}")
    print(f"测试脚本：{TESTS_DIR / 'test_generated_api.py'}")
    print(f"测试报告：{TEST_REPORT_PATH}")


if __name__ == "__main__":
    main()
