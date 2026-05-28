"""接口采集：Playwright 抓包、清洗、脱敏。"""

from capture.capture import (
    api_request_dedup_key,
    capture_api_requests,
    load_cookies_from_file,
    url_matches_filters,
)
from capture.cleaner import build_llm_input

__all__ = [
    "capture_api_requests",
    "api_request_dedup_key",
    "load_cookies_from_file",
    "url_matches_filters",
    "build_llm_input",
]
