"""接口知识库读写与增量合并。"""

import copy
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from capture import url_matches_filters


KB_VERSION = 1
DEFAULT_INCLUDE_IN_TESTS = True
PRESERVED_FIELDS = (
    "include_in_tests",
    "test_skip_reason",
    "tags",
    "kb_notes",
    "owner",
    "locked",
    "manual_overrides",
)
COMMON_API_PATTERNS = (
    ("api/config/*", "公共配置接口，无需加入接口回放测试", ["common", "config"]),
    ("api/search/config", "搜索配置接口，无需加入接口回放测试", ["common", "config"]),
    ("api/ad", "广告接口，无需加入接口回放测试", ["common", "ad"]),
    ("api/synclogin/*", "登录同步接口依赖会话/签名，回放测试不稳定", ["common", "auth"]),
    ("resources/*", "静态资源接口，无需加入接口回放测试", ["common", "static"]),
)


def load_api_knowledge_base(kb_file):
    """读取接口知识库；文件不存在时返回空知识库。"""
    path = Path(kb_file)
    if not path.exists():
        return {"version": KB_VERSION, "apis": []}

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"知识库格式错误，应为 JSON 对象：{kb_file}")
    data.setdefault("version", KB_VERSION)
    data.setdefault("apis", [])
    return data


def save_api_knowledge_base(kb, kb_file):
    """保存接口知识库。"""
    path = Path(kb_file)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(kb, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def merge_api_knowledge_base(analysis_results, kb_file, skip_test_filters=None, overwrite=False):
    """将本次分析结果合并进固定知识库，并返回可用于文档/测试的结果列表。"""
    kb = {"version": KB_VERSION, "apis": []} if overwrite else load_api_knowledge_base(kb_file)
    existing = {_entry_key(entry): entry for entry in kb.get("apis", [])}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for item in analysis_results:
        entry = _entry_from_analysis_result(item, now)
        key = _entry_key(entry)
        previous = existing.get(key)
        if previous:
            entry = _merge_entry(previous, entry, skip_test_filters)
        else:
            entry = _apply_common_api_defaults(entry)
            entry = _apply_skip_filters(entry, skip_test_filters)
        existing[key] = entry

    if skip_test_filters:
        existing = {
            key: _apply_skip_filters(entry, skip_test_filters)
            for key, entry in existing.items()
        }

    kb["apis"] = sorted(existing.values(), key=lambda item: item.get("id", ""))
    save_api_knowledge_base(kb, kb_file)
    return knowledge_base_to_analysis_results(kb)


def get_known_api_keys(kb_file):
    """读取知识库中已经处理过的接口 key。"""
    kb = load_api_knowledge_base(kb_file)
    return {_entry_key(entry) for entry in kb.get("apis", [])}


def build_api_key(source):
    """按现有知识库粒度生成接口 key：方法 + 域名 + 路径。"""
    return _make_id(
        source.get("method"),
        source.get("domain"),
        source.get("path"),
    )


def knowledge_base_to_analysis_results(kb):
    """将知识库结构转换为现有文档/测试生成器可消费的数据结构。"""
    results = []
    for entry in kb.get("apis", []):
        result = {
            "raw": copy.deepcopy(entry.get("raw") or {}),
            "source": copy.deepcopy(entry.get("source") or {}),
            "analysis": copy.deepcopy(entry.get("analysis") or {}),
            "include_in_tests": entry.get("include_in_tests", DEFAULT_INCLUDE_IN_TESTS),
            "test_skip_reason": entry.get("test_skip_reason", ""),
            "tags": copy.deepcopy(entry.get("tags") or []),
            "kb_notes": entry.get("kb_notes", ""),
        }
        results.append(result)
    return results


def _entry_from_analysis_result(item, now):
    raw = copy.deepcopy(item.get("raw") or {})
    source = copy.deepcopy(item.get("source") or {})
    analysis = copy.deepcopy(item.get("analysis") or {})
    method = (analysis.get("method") or source.get("method") or raw.get("method") or "").upper()
    path = analysis.get("path") or source.get("path") or urlparse(raw.get("url", "")).path
    domain = source.get("domain") or urlparse(raw.get("url", "")).netloc

    return {
        "id": _make_id(method, domain, path),
        "method": method,
        "domain": domain,
        "path": path,
        "include_in_tests": DEFAULT_INCLUDE_IN_TESTS,
        "test_skip_reason": "",
        "tags": [],
        "kb_notes": "",
        "locked": False,
        "source": source,
        "analysis": analysis,
        "raw": raw,
        "created_at": now,
        "updated_at": now,
    }


def _merge_entry(previous, current, skip_test_filters):
    if previous.get("locked"):
        entry = copy.deepcopy(previous)
        entry = _apply_skip_filters(entry, skip_test_filters)
        return entry

    entry = copy.deepcopy(current)
    entry["created_at"] = previous.get("created_at") or current.get("created_at")

    for field in PRESERVED_FIELDS:
        if field in previous:
            entry[field] = copy.deepcopy(previous[field])

    entry = _apply_manual_overrides(entry)
    entry = _apply_skip_filters(entry, skip_test_filters)
    return entry


def _apply_manual_overrides(entry):
    overrides = entry.get("manual_overrides") or {}
    if not isinstance(overrides, dict):
        return entry

    for section in ("analysis", "source", "raw"):
        patch = overrides.get(section)
        if isinstance(patch, dict):
            base = copy.deepcopy(entry.get(section) or {})
            base.update(patch)
            entry[section] = base
    return entry


def _add_tags(entry, tags):
    current = list(entry.get("tags") or [])
    for tag in tags:
        if tag not in current:
            current.append(tag)
    entry["tags"] = current
    return entry


def _apply_common_api_defaults(entry):
    raw_url = (entry.get("raw") or {}).get("url") or entry.get("path") or ""
    path = entry.get("path") or raw_url
    for pattern, reason, tags in COMMON_API_PATTERNS:
        if url_matches_filters(raw_url, [pattern]) or url_matches_filters(path, [pattern]):
            entry["include_in_tests"] = False
            entry["test_skip_reason"] = entry.get("test_skip_reason") or reason
            entry = _add_tags(entry, tags + ["low_value_test"])
            break
    return entry


def _apply_skip_filters(entry, skip_test_filters):
    filters = skip_test_filters or []
    raw_url = (entry.get("raw") or {}).get("url") or entry.get("path") or ""
    path = entry.get("path") or raw_url
    if filters and (
        url_matches_filters(raw_url, filters)
        or url_matches_filters(path, filters)
    ):
        entry["include_in_tests"] = False
        entry["test_skip_reason"] = entry.get("test_skip_reason") or "匹配公共接口过滤规则"
        entry = _add_tags(entry, ["common"])
    return entry


def _entry_key(entry):
    method = entry.get("method") or (entry.get("source") or {}).get("method")
    domain = entry.get("domain") or (entry.get("source") or {}).get("domain")
    path = entry.get("path") or (entry.get("source") or {}).get("path")
    return _make_id(method, domain, path)


def _make_id(method, domain, path):
    return f"{(method or '').upper()} {domain or ''} {path or ''}".strip()
