import json

from testing.script_generator import (
    build_parameter_rules,
    enrich_success_criteria_from_capture,
    generate_pytest_suite,
    load_replay_cookies,
)


def make_analysis_result():
    return [{
        "raw": {
            "method": "GET",
            "url": "https://example.com/api/user/profile",
            "status": 200,
            "request_headers": {},
            "content_type": "application/json",
            "response_body_preview": {"code": 0},
        },
        "source": {
            "method": "GET",
            "domain": "example.com",
            "path": "/api/user/profile",
        },
        "analysis": {
            "api_name": "用户信息",
            "description": "获取用户信息",
            "success_criteria": {"http_status": {"ok": [200]}, "json": {}},
            "response_rules": {"content_type_contains": "application/json"},
        },
    }]


def make_query_required_analysis_result():
    result = make_analysis_result()
    result[0]["raw"]["url"] = "https://example.com/api/user/profile?id=1"
    result[0]["analysis"]["parameter_rules"] = [{
        "name": "id",
        "in": "query",
        "type": "string",
        "required": "true",
        "description": "用户 ID",
    }]
    return result


def make_query_unknown_analysis_result():
    result = make_analysis_result()
    result[0]["raw"]["url"] = "https://example.com/api/user/profile?id=1"
    result[0]["source"]["query_params"] = {"id": "number"}
    result[0]["analysis"]["parameter_rules"] = [{
        "name": "id",
        "in": "query",
        "type": "number",
        "required": "unknown",
        "description": "用户 ID",
    }]
    return result


def test_load_replay_cookies_from_storage_state(tmp_path):
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(
        json.dumps({
            "cookies": [
                {
                    "name": "sid",
                    "value": "abc",
                    "domain": ".example.com",
                    "path": "/",
                }
            ],
            "origins": [],
        }),
        encoding="utf-8",
    )

    cookies = load_replay_cookies(cookie_file, "https://example.com")

    assert cookies == [
        {"name": "sid", "value": "abc", "domain": ".example.com", "path": "/"}
    ]


def test_generated_conftest_applies_replay_cookies(tmp_path):
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text('{"sid": "abc"}', encoding="utf-8")
    tests_dir = tmp_path / "generated_tests"

    generate_pytest_suite(
        make_analysis_result(),
        tests_dir,
        page_url="https://example.com",
        cookie_file=cookie_file,
    )

    conftest = (tests_dir / "conftest.py").read_text(encoding="utf-8")
    assert "REPLAY_COOKIES" in conftest
    assert "'name': 'sid'" in conftest
    assert "session.cookies.set" in conftest


def test_missing_query_param_negative_case_sends_request_without_payload(tmp_path):
    tests_dir = tmp_path / "generated_tests"

    generate_pytest_suite(
        make_query_required_analysis_result(),
        tests_dir,
        page_url="https://example.com",
    )

    generated = (tests_dir / "test_generated_api.py").read_text(encoding="utf-8")
    assert "else:\n        response = http_session.request(\"GET\", url, headers=headers, timeout=30)" in generated


def test_enrich_success_criteria_handles_repr_string_code_200():
    raw = {
        "response_body_preview": "{'data': 'encrypted', 'code': 200, 'msg': '成功'}",
        "content_type": "text/html; charset=utf-8",
    }
    criteria = {
        "json": {
            "must_exist_paths": [],
            "code_path": "code",
            "ok_codes": [0],
        }
    }

    enriched = enrich_success_criteria_from_capture(raw, criteria)

    assert enriched["json"]["ok_codes"] == [200]
    assert "code" in enriched["json"]["must_exist_paths"]


def test_enrich_success_criteria_does_not_treat_404_as_ok_code():
    raw = {
        "response_body_preview": "{'data': 'encrypted', 'code': 404, 'msg': '未找到数据'}",
        "content_type": "text/html; charset=utf-8",
    }
    criteria = {
        "json": {
            "must_exist_paths": [],
            "success_path": "data",
            "success_values": ["encrypted"],
            "code_path": "code",
            "ok_codes": [0],
        }
    }

    enriched = enrich_success_criteria_from_capture(raw, criteria)

    assert enriched["json"]["ok_codes"] == []
    assert enriched["json"]["sample_error_code"] == 404
    assert enriched["json"]["success_path"] == ""
    assert "success_values" not in enriched["json"]


def test_build_parameter_rules_adds_observed_query_params():
    rules = build_parameter_rules(
        {"parameter_rules": []},
        {"query_params": {"page": "number"}},
    )

    assert rules == [{
        "name": "page",
        "in": "query",
        "type": "number",
        "required": "unknown",
        "description": "抓包中出现的 query 参数",
    }]


def test_unknown_required_param_is_used_as_negative_candidate(tmp_path):
    tests_dir = tmp_path / "generated_tests"

    generate_pytest_suite(
        make_query_unknown_analysis_result(),
        tests_dir,
        page_url="https://example.com",
    )

    generated = (tests_dir / "test_generated_api.py").read_text(encoding="utf-8")
    assert "required')).lower() == 'unknown'" in generated
    assert "pytest.skip('无可测必填参数规则')" not in generated
