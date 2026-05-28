"""根据抓包记录与 LLM 分析结果生成 pytest 接口测试脚本。"""

import ast
import copy
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from capture import load_cookies_from_file

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
    """将任意字符串转为合法 Python 标识符片段。"""
    slug = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    slug = re.sub(r"_+", "_", slug).strip("_")
    if not slug:
        slug = "api"
    if slug[0].isdigit():
        slug = f"api_{slug}"
    return slug[:max_len]


def should_skip_domain(domain, page_domain=None):
    """判断是否跳过该域名的接口测试。"""
    domain = (domain or "").lower()
    if any(domain.endswith(suffix) for suffix in SKIP_DOMAIN_SUFFIXES):
        return True
    if page_domain:
        page_domain = page_domain.lower().lstrip("www.")
        host = domain.lstrip("www.")
        if host != page_domain and not host.endswith(f".{page_domain}"):
            return True
    return False


def _request_content_type(raw):
    """从请求头推断请求体 Content-Type。"""
    headers = (raw or {}).get("request_headers") or {}
    for key, value in headers.items():
        if key.lower() == "content-type":
            return value or ""
    return ""


def pick_request_headers(headers):
    """从抓包记录中挑选可回放的请求头。"""
    picked = {}
    for key, value in (headers or {}).items():
        if key.lower() not in ALLOWED_HEADERS:
            continue
        if value == "***":
            continue
        picked[key] = value
    return picked


def _parse_response_preview(raw):
    """从抓包记录的 response_body_preview 解析 JSON 对象。"""
    preview = (raw or {}).get("response_body_preview")
    if isinstance(preview, dict):
        return preview
    if isinstance(preview, str):
        text = preview.strip()
        if not text.startswith("{"):
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                return None
            return parsed if isinstance(parsed, dict) else None
    return None


def enrich_success_criteria_from_capture(raw, success_criteria):
    """用抓包样本校正业务断言，避免 LLM 臆造 ok_codes=200 而样本为 401。"""
    observed = _parse_response_preview(raw)
    if not isinstance(observed, dict):
        return success_criteria or {}

    criteria = copy.deepcopy(success_criteria or {})
    json_criteria = criteria.setdefault("json", {})

    for key in ("data", "code", "msg", "message", "success"):
        if key in observed:
            path = key
            paths = json_criteria.setdefault("must_exist_paths", [])
            if path not in paths:
                paths.append(path)

    if "code" in observed:
        json_criteria["code_path"] = json_criteria.get("code_path") or "code"
        json_criteria["ok_codes"] = [observed["code"]]
        # 样本为错误码时，不用 LLM 臆造的 data 成功值做断言
        if observed["code"] not in (0, 200, "0", "200"):
            json_criteria.pop("success_values", None)
            if json_criteria.get("success_path") in ("data", "result", "payload"):
                json_criteria["success_path"] = ""

    if "success" in observed and isinstance(observed["success"], bool):
        json_criteria["success_path"] = json_criteria.get("success_path") or "success"
        json_criteria["success_values"] = [observed["success"]]

    # 回放测试：content-type 以实际响应为准
    content_type = (raw or {}).get("content_type") or ""
    response_rules = criteria.setdefault("_response_rules_patch", {})
    if content_type:
        response_rules["content_type_contains"] = content_type.split(";")[0].strip()

    return criteria


def _py_literal(obj):
    """生成可嵌入 Python 源码的字面量（使用 repr，避免 JSON 的 null）。"""
    return repr(obj)


def load_replay_cookies(cookie_file, page_url=None):
    """加载用于 requests 回放测试的 cookie。"""
    if not cookie_file:
        return []
    try:
        cookies = load_cookies_from_file(cookie_file, page_url or "http://localhost/")
    except Exception as e:
        print(f"测试回放 cookie 加载失败：{e}")
        return []

    replay_cookies = []
    for cookie in cookies:
        item = {
            "name": cookie.get("name"),
            "value": cookie.get("value"),
            "domain": cookie.get("domain"),
            "path": cookie.get("path") or "/",
        }
        if not item["domain"] and cookie.get("url"):
            item["domain"] = urlparse(cookie["url"]).hostname
        if item["name"] and item["value"] is not None:
            replay_cookies.append(item)
    return replay_cookies


def build_parameter_rules(analysis, source):
    """合并 LLM 参数规则与抓包中真实出现的参数。"""
    rules = copy.deepcopy(
        analysis.get("parameter_rules")
        or analysis.get("request_params")
        or []
    )
    seen = {
        (rule.get("in"), rule.get("name"))
        for rule in rules
        if rule.get("in") and rule.get("name")
    }

    for name, value_type in (source.get("query_params") or {}).items():
        key = ("query", name)
        if key in seen:
            continue
        rules.append({
            "name": name,
            "in": "query",
            "type": value_type or "unknown",
            "required": "unknown",
            "description": "抓包中出现的 query 参数",
        })
        seen.add(key)

    body_schema = source.get("request_body_schema")
    if isinstance(body_schema, dict):
        for name, value_type in body_schema.items():
            key = ("body", name)
            if key in seen:
                continue
            rules.append({
                "name": name,
                "in": "body",
                "type": value_type if isinstance(value_type, str) else "object",
                "required": "unknown",
                "description": "抓包中出现的 body 参数",
            })
            seen.add(key)

    return rules


def build_test_cases(analysis_results, page_url=None):
    """从分析结果构建可生成脚本的测试用例元数据。"""
    page_domain = urlparse(page_url).netloc if page_url else None
    cases = []

    for index, item in enumerate(analysis_results, start=1):
        if item.get("include_in_tests") is False:
            continue

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

        success_criteria = enrich_success_criteria_from_capture(
            raw, analysis.get("success_criteria") or {}
        )
        response_rules = copy.deepcopy(analysis.get("response_rules") or {})
        patch = success_criteria.pop("_response_rules_patch", None)
        if patch:
            response_rules.update(patch)
        content_type = (raw.get("content_type") or "").split(";")[0].strip()
        if content_type and not response_rules.get("content_type_contains"):
            response_rules["content_type_contains"] = content_type

        parameter_rules = build_parameter_rules(analysis, source)
        cases.append({
            "func_name": func_name,
            "api_name": api_name,
            "method": method,
            "url": url,
            "expected_status": raw.get("status", 200),
            "headers": pick_request_headers(raw.get("request_headers")),
            "request_body": raw.get("request_body"),
            "content_type": _request_content_type(raw),
            "description": analysis.get("description", ""),
            "success_criteria": success_criteria,
            "parameter_rules": parameter_rules,
            "request_params": analysis.get("request_params") or [],
            "response_fields": analysis.get("response_fields") or [],
            "response_rules": response_rules,
        })

    return cases


def _render_conftest(replay_cookies):
    cookies_repr = _py_literal(replay_cookies)
    return "\n".join([
        '"""自动生成的 pytest 配置。"""',
        "",
        "import pytest",
        "import requests",
        "",
        f"REPLAY_COOKIES = {cookies_repr}",
        "",
        "",
        "def _apply_replay_cookies(session):",
        '    """将采集阶段保存的 cookie 注入 requests 会话。"""',
        "    for cookie in REPLAY_COOKIES:",
        "        session.cookies.set(",
        "            cookie['name'],",
        "            cookie['value'],",
        "            domain=cookie.get('domain'),",
        "            path=cookie.get('path') or '/',",
        "        )",
        "",
        "",
        "@pytest.fixture(scope='session')",
        "def http_session():",
        '    """共享 HTTP 会话。"""',
        "    session = requests.Session()",
        "    _apply_replay_cookies(session)",
        "    yield session",
        "    session.close()",
        "",
    ])


def generate_pytest_suite(analysis_results, tests_dir, page_url=None, cookie_file=None):
    """生成 pytest 测试目录（conftest + 测试模块）。"""
    tests_path = Path(tests_dir)
    tests_path.mkdir(parents=True, exist_ok=True)

    cases = build_test_cases(analysis_results, page_url)
    if not cases:
        return cases

    replay_cookies = load_replay_cookies(cookie_file, page_url)
    conftest = tests_path / "conftest.py"
    conftest.write_text(_render_conftest(replay_cookies), encoding="utf-8")

    lines = [
        '"""自动生成的接口回放测试，请勿手动修改。"""',
        "",
        "import json",
        "import pytest",
        "from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse",
        "",
        "",
        "def _get_by_path(obj, path):",
        '    """按点号路径读取 JSON 值，例如 data.list[0].id。"""',
        "    if not path:",
        "        return None",
        "    cur = obj",
        "    for part in path.split('.'):",
        "        if cur is None:",
        "            return None",
        "        if '[' in part and part.endswith(']'):",
        "            name, idx = part[:-1].split('[', 1)",
        "            if name:",
        "                if not isinstance(cur, dict):",
        "                    return None",
        "                cur = cur.get(name)",
        "            try:",
        "                i = int(idx)",
        "            except ValueError:",
        "                return None",
        "            if not isinstance(cur, list) or i >= len(cur):",
        "                return None",
        "            cur = cur[i]",
        "        else:",
        "            if not isinstance(cur, dict):",
        "                return None",
        "            cur = cur.get(part)",
        "    return cur",
        "",
        "",
        "def _try_parse_json(response):",
        "    try:",
        "        return response.json()",
        "    except Exception:",
        "        pass",
        "    try:",
        "        return json.loads(response.text)",
        "    except Exception:",
        "        return None",
        "",
    ]

    for case in cases:
        lines.extend(_render_test_functions(case))

    test_file = tests_path / "test_generated_api.py"
    test_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return cases


def _render_test_functions(case):
    """渲染单条接口对应的 pytest 测试函数源码行。"""
    func_name = case["func_name"]
    doc = (case.get("description") or case["api_name"]).replace('"', "'")
    headers_repr = _py_literal(case["headers"])
    url_repr = _py_literal(case["url"])
    method = case["method"]
    expected = case["expected_status"]
    body = case.get("request_body")
    if isinstance(body, str) and body.startswith("[binary:"):
        body = None
    content_type = (case.get("content_type") or "").lower()
    success_criteria = case.get("success_criteria") or {}
    response_rules = case.get("response_rules") or {}
    parameter_rules = case.get("parameter_rules") or []
    criteria_repr = _py_literal(success_criteria)
    response_rules_repr = _py_literal(response_rules)
    param_rules_repr = _py_literal(parameter_rules)
    body_text_literal = _py_literal(body) if body else "None"

    lines = [
        f"def test_{func_name}_ok(http_session):",
        f'    """{doc}"""',
        f"    url = {url_repr}",
        f"    headers = {headers_repr}",
        f"    expected_status = {expected}",
        f"    success_criteria = {criteria_repr}",
        f"    response_rules = {response_rules_repr}",
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
        "    ok_status = (success_criteria.get('http_status') or {}).get('ok') or [expected_status]",
        "    assert response.status_code in ok_status, (",
        "        f\"期望状态码 in {ok_status}，实际 {response.status_code}，\"",
        "        f\"body={response.text[:300]}\"",
        "    )",
        "",
        "    expected_ct = (response_rules.get('content_type_contains') or '').lower().strip()",
        "    if expected_ct:",
        "        actual_ct = (response.headers.get('content-type') or '').lower()",
        "        assert expected_ct in actual_ct, f\"content-type 应包含 {expected_ct}，实际 {actual_ct}\"",
        "",
        "    data = _try_parse_json(response)",
        "    if data is not None:",
        "        json_criteria = success_criteria.get('json') or {}",
        "        for p in (json_criteria.get('must_exist_paths') or []):",
        "            assert _get_by_path(data, p) is not None, f\"响应缺少字段路径: {p}\"",
        "        for p in (response_rules.get('must_exist_paths') or []):",
        "            assert _get_by_path(data, p) is not None, f\"响应缺少字段路径: {p}\"",
        "        success_path = (json_criteria.get('success_path') or '').strip()",
        "        success_values = json_criteria.get('success_values') or []",
        "        code_path = (json_criteria.get('code_path') or '').strip()",
        "        ok_codes = json_criteria.get('ok_codes') or []",
        "        if success_path and success_values:",
        "            v = _get_by_path(data, success_path)",
        "            assert v in success_values, f\"业务成功字段 {success_path}={v}，期望 in {success_values}\"",
        "        if code_path and ok_codes:",
        "            v = _get_by_path(data, code_path)",
        "            assert v in ok_codes, f\"业务码字段 {code_path}={v}，期望 in {ok_codes}\"",
        "",
    ])

    lines.extend([
        f"def test_{func_name}_missing_required_param(http_session):",
        f'    """负例：缺少参数时应失败或产生可判定变化。"""',
        f"    base_url = {url_repr}",
        f"    headers = {headers_repr}",
        f"    rules = {param_rules_repr}",
        f"    success_criteria = {criteria_repr}",
        "",
        "    candidates = [r for r in rules if str(r.get('required')).lower() == 'true' and r.get('in') in ('query','body') and r.get('name')]",
        "    if not candidates:",
        "        candidates = [r for r in rules if str(r.get('required')).lower() == 'unknown' and r.get('in') in ('query','body') and r.get('name')]",
        "    if not candidates:",
        "        pytest.skip('无可测参数规则')",
        "    target = candidates[0]",
        "    location = target.get('in')",
        "    name = target.get('name')",
        "",
        "    url = base_url",
        "    payload = None",
        "    if location == 'query':",
        "        u = urlparse(base_url)",
        "        q = [(k, v) for (k, v) in parse_qsl(u.query, keep_blank_values=True) if k != name]",
        "        url = urlunparse((u.scheme, u.netloc, u.path, u.params, urlencode(q, doseq=True), u.fragment))",
        "    elif location == 'body':",
        f"        body_text = {body_text_literal}",
        "        try:",
        "            payload = json.loads(body_text) if isinstance(body_text, str) else None",
        "        except Exception:",
        "            payload = None",
        "        if isinstance(payload, dict) and name in payload:",
        "            payload.pop(name, None)",
        "        else:",
        "            pytest.skip('无法从抓包 body 构造缺参负例')",
        "",
        "    if payload is not None:",
    ])
    if "application/json" in content_type:
        lines.append(
            f'        response = http_session.request("{method}", url, headers=headers, json=payload, timeout=30)'
        )
    else:
        lines.append(
            f'        response = http_session.request("{method}", url, headers=headers, data=payload, timeout=30)'
        )
    lines.extend([
        "    else:",
        f'        response = http_session.request("{method}", url, headers=headers, timeout=30)',
        "",
        "",
        "    ok_status = (success_criteria.get('http_status') or {}).get('ok') or [200]",
        "    data = _try_parse_json(response)",
        "    if data is not None:",
        "        json_criteria = success_criteria.get('json') or {}",
        "        code_path = (json_criteria.get('code_path') or '').strip()",
        "        ok_codes = json_criteria.get('ok_codes') or []",
        "        if code_path and ok_codes:",
        "            v = _get_by_path(data, code_path)",
        "            if v in ok_codes:",
        "                pytest.skip('缺参后业务码未变化，无法判定负例')",
        "            return",
        "        success_path = (json_criteria.get('success_path') or '').strip()",
        "        success_values = json_criteria.get('success_values') or []",
        "        if success_path and success_values:",
        "            v = _get_by_path(data, success_path)",
        "            if v in success_values:",
        "                pytest.skip('缺参后响应未变化，无法判定负例')",
        "            return",
        "    if response.status_code in ok_status:",
        "        pytest.skip('缺参后仍返回成功状态，无法判定负例')",
        "",
    ])

    return lines
