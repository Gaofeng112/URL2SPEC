import json

from report.knowledge_base import (
    build_api_key,
    get_known_api_keys,
    load_api_knowledge_base,
    merge_api_knowledge_base,
)
from testing.script_generator import build_test_cases


def make_result(path="/api/zgqxss/list", method="GET", domain="example.com"):
    url = f"https://{domain}{path}"
    return {
        "raw": {
            "method": method,
            "url": url,
            "status": 200,
            "request_headers": {},
            "content_type": "application/json",
            "response_body_preview": {"code": 0, "data": []},
        },
        "source": {
            "method": method,
            "domain": domain,
            "path": path,
            "query_params": {},
        },
        "analysis": {
            "api_name": "列表接口",
            "method": method,
            "path": path,
            "description": "获取列表",
            "success_criteria": {
                "http_status": {"ok": [200]},
                "json": {"must_exist_paths": ["code"], "code_path": "code", "ok_codes": [0]},
            },
            "response_rules": {"content_type_contains": "application/json"},
        },
    }


def test_merge_knowledge_base_creates_stable_file(tmp_path):
    kb_file = tmp_path / "api_knowledge_base.json"

    results = merge_api_knowledge_base([make_result()], kb_file)
    kb = load_api_knowledge_base(kb_file)

    assert kb["version"] == 1
    assert len(kb["apis"]) == 1
    assert kb["apis"][0]["id"] == "GET example.com /api/zgqxss/list"
    assert results[0]["include_in_tests"] is True


def test_merge_knowledge_base_preserves_manual_test_skip(tmp_path):
    kb_file = tmp_path / "api_knowledge_base.json"
    merge_api_knowledge_base([make_result()], kb_file)

    data = json.loads(kb_file.read_text(encoding="utf-8"))
    data["apis"][0]["include_in_tests"] = False
    data["apis"][0]["test_skip_reason"] = "公共接口"
    data["apis"][0]["tags"] = ["common"]
    kb_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    results = merge_api_knowledge_base([make_result()], kb_file)

    assert results[0]["include_in_tests"] is False
    assert results[0]["test_skip_reason"] == "公共接口"
    assert results[0]["tags"] == ["common"]
    assert build_test_cases(results, "https://example.com") == []


def test_merge_knowledge_base_marks_common_api_by_filter(tmp_path):
    kb_file = tmp_path / "api_knowledge_base.json"

    results = merge_api_knowledge_base(
        [make_result(path="/api/common/dict")],
        kb_file,
        skip_test_filters=["api/common/*"],
    )

    assert results[0]["include_in_tests"] is False
    assert "公共接口" in results[0]["test_skip_reason"]


def test_merge_knowledge_base_applies_common_api_defaults(tmp_path):
    kb_file = tmp_path / "api_knowledge_base.json"

    results = merge_api_knowledge_base(
        [make_result(path="/api/config/navv2")],
        kb_file,
    )

    assert results[0]["include_in_tests"] is False
    assert "配置接口" in results[0]["test_skip_reason"]
    assert "common" in results[0]["tags"]
    assert "low_value_test" in results[0]["tags"]


def test_merge_knowledge_base_preserves_manual_include_decision(tmp_path):
    kb_file = tmp_path / "api_knowledge_base.json"
    merge_api_knowledge_base([make_result(path="/api/config/navv2")], kb_file)

    data = json.loads(kb_file.read_text(encoding="utf-8"))
    data["apis"][0]["include_in_tests"] = True
    data["apis"][0]["test_skip_reason"] = ""
    data["apis"][0]["tags"] = ["manual_core"]
    kb_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    results = merge_api_knowledge_base([make_result(path="/api/config/navv2")], kb_file)

    assert results[0]["include_in_tests"] is True
    assert results[0]["test_skip_reason"] == ""
    assert results[0]["tags"] == ["manual_core"]


def test_known_api_keys_can_skip_repeated_llm_analysis(tmp_path):
    kb_file = tmp_path / "api_knowledge_base.json"
    merge_api_knowledge_base([make_result()], kb_file)

    known_keys = get_known_api_keys(kb_file)
    current_key = build_api_key({
        "method": "GET",
        "domain": "example.com",
        "path": "/api/zgqxss/list",
    })

    assert current_key in known_keys


def test_merge_knowledge_base_overwrite_replaces_existing_entries(tmp_path):
    kb_file = tmp_path / "api_knowledge_base.json"
    merge_api_knowledge_base([make_result(path="/api/old")], kb_file)

    results = merge_api_knowledge_base(
        [make_result(path="/api/new")],
        kb_file,
        overwrite=True,
    )
    kb = load_api_knowledge_base(kb_file)

    assert [api["path"] for api in kb["apis"]] == ["/api/new"]
    assert [item["source"]["path"] for item in results] == ["/api/new"]
