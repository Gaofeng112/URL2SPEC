"""用户示例：单独运行交互式接口抓包。

用法（在项目根目录执行）：
    python test/example_capture.py
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from capture import capture_api_requests


def main():
    page_url = "https://vip.yaozh.com"
    records = capture_api_requests(page_url)
    print(f"共捕获 {len(records)} 条接口")


if __name__ == "__main__":
    main()
