import os
import sys

# 允许直接运行：python test/test_capture.py
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from crawler.capture import capture_api_requests

# 交互式（默认）
records = capture_api_requests("https://vip.yaozh.com")

# # 非交互，固定等待 8 秒
# records = capture_api_requests("https://www.yaozh.com/", interactive=False, wait_seconds=8)