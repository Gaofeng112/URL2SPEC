"""根据抓包记录与 LLM 分析结果生成 pytest 接口测试脚本。"""

import json
import re
from pathlib import Path
from urllib.parse import urlparse

# 默认跳过第三方统计/埋点域名，避免无关失败。
SKIP_DOMAIN_SUFFIXES = (
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "facebook.net",
)

# 回放请求时允许携带的非敏感头。
ALLOWED_HEADERS = {
    "user-agent",
    "accept",
    "referer",
    "x-requested-with",
    "content-type",
    "accept-language",
}


def slugify(name, max_len=48):
    """将任意字符串转为合法 Python 标识符片段。

    Args:
        name: 原始名称（通常为 URL path）。
        max_len: 最大长度。

    Returns:
        合法标识符字符串。
    """
    slug = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    slug = re.sub(r"_+", "_", slug).strip("_")
    if not slug:
        slug = "api"
    if slug[0].isdigit():
        slug = f"api_{slug}"
    return slug[:max_len]


def should_skip_domain(domain, page_domain=None):
    """判断是否跳过该域名的接口测试。

    Args:
        domain: 接口域名。
        page_domain: 页面主域名；若提供则仅测试同域或子域接口。

    Returns:
        为 ``True`` 时跳过生成测试。
    """
    domain = (domain or "").lower()
    if any(domain.endswith(suffix) for suffix in SKIP_DOMAIN_SUFFIXES):
        return True
    if page_domain:
        page_domain = page_domain.lower().lstrip("www.")
        host = domain.lstrip("www.")
        if host != page_domain and not host.endswith(f".{page_domain}"):
            return True
    return False


def pick_request_headers(headers):
    """从抓包记录中挑选可回放的请求头。

    Args:
        headers: 已脱敏的请求头字典。

    Returns:
        仅包含白名单且值未被脱敏的请求头。
    """
    picked = {}
    for key, value in (headers or {}).items():
        if key.lower() not in ALLOWED_HEADERS:
            continue
        if value == "***":
            continue
        picked[key] = value
    return picked


def build_test_cases(analysis_results, page_url=None):
    """从分析结果构建可生成脚本的测试用例元数据。

    Args:
        analysis_results: 含 ``raw``、``source``、``analysis`` 的列表。
        page_url: 用户输入的页面 URL，用于过滤第三方域名。

    Returns:
        测试用例字典列表。
    """
    page_domain = urlparse(page_url).netloc if page_url else None
    cases = []

    for index, item in enumerate(analysis_results, start=1):
        raw = item.get("raw") or {}
        source = item.get("source") or {}
        analysis = item.get("analysis") or {}

        domain = source.get("domain") or urlparse(raw.get("url", "")).netloc
        if should_skip_domain(domain, page_domain):
            continue

        url = raw.get("url")
        if not url:
            continue

        method = (raw.get("method") or "GET").upper()
        path = source.get("path") or urlparse(url).path
        api_name = analysis.get("api_name") or path
        func_name = slugify(f"{index}_{method}_{path}")

        cases.append({
            "func_name": func_name,
            "api_name": api_name,
            "method": method,
            "url": url,
            "expected_status": raw.get("status", 200),
            "headers": pick_request_headers(raw.get("request_headers")),
            "request_body": raw.get("request_body"),
            "content_type": raw.get("content_type", ""),
            "description": analysis.get("description", ""),
        })

    return cases


def generate_pytest_suite(analysis_results, tests_dir, page_url=None):
    """生成 pytest 测试目录（conftest + 测试模块）。

    Args:
        analysis_results: 含 ``raw`` 抓包数据的分析结果列表。
        tests_dir: 输出目录路径。
        page_url: 页面 URL，用于同域过滤。

    Returns:
        生成的测试用例元数据列表。
    """
    tests_path = Path(tests_dir)
    tests_path.mkdir(parents=True, exist_ok=True)

    cases = build_test_cases(analysis_results, page_url)
    if not cases:
        return cases

    conftest = tests_path / "conftest.py"
    conftest.write_text(
        '"""自动生成的 pytest 配置。"""\n\n'
        "import pytest\nimport requests\n\n\n"
        "@pytest.fixture(scope='session')\n"
        "def http_session():\n"
        '    """共享 HTTP 会话。"""\n'
        "    session = requests.Session()\n"
        "    yield session\n"
        "    session.close()\n",
        encoding="utf-8",
    )

    lines = [
        '"""自动生成的接口回放测试，请勿手动修改。"""',
        "",
        "import json",
        "",
        "",
    ]

    for case in cases:
        lines.extend(_render_test_function(case))

    test_file = tests_path / "test_generated_api.py"
    test_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return cases


def _render_test_function(case):
    """渲染单条 pytest 测试函数源码行。

    Args:
        case: ``build_test_cases`` 返回的单项。

    Returns:
        源码行列表。
    """
    func_name = case["func_name"]
    doc = (case.get("description") or case["api_name"]).replace('"', "'")
    headers_repr = json.dumps(case["headers"], ensure_ascii=False, indent=4)
    url_repr = json.dumps(case["url"], ensure_ascii=False)
    method = case["method"]
    expected = case["expected_status"]
    body = case.get("request_body")
    if isinstance(body, str) and body.startswith("[binary:"):
        body = None
    content_type = (case.get("content_type") or "").lower()

    lines = [
        f"def test_{func_name}(http_session):",
        f'    """{doc}"""',
        f"    url = {url_repr}",
        f"    headers = {headers_repr}",
        f"    expected_status = {expected}",
    ]

    if body and "application/json" in content_type:
        body_literal = json.dumps(body, ensure_ascii=False)
        lines.append(f"    payload = json.loads({body_literal})")
        lines.append(
            f"    response = http_session.request("
            f'"{method}", url, headers=headers, json=payload, timeout=30)'
        )
    elif body:
        body_literal = json.dumps(body, ensure_ascii=False)
        lines.append(f"    payload = {body_literal}")
        lines.append(
            f"    response = http_session.request("
            f'"{method}", url, headers=headers, data=payload, timeout=30)'
        )
    else:
        lines.append(
            f"    response = http_session.request("
            f'"{method}", url, headers=headers, timeout=30)'
        )

    lines.extend([
        f"    assert response.status_code == expected_status, (",
        f'        f"期望 {{expected_status}}，实际 {{response.status_code}}，"'
        f" f\"body={{response.text[:300]}}\"",
        "    )",
        "",
    ])
    return lines
