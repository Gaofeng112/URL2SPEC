"""接口采集：Playwright 抓包、清洗、脱敏。"""

from capture.capture import capture_api_requests
from capture.cleaner import build_llm_input

__all__ = ["capture_api_requests", "build_llm_input"]
