"""测试：脚本生成、pytest 执行。"""

from testing.runner import run_pytest_suite
from testing.script_generator import generate_pytest_suite

__all__ = ["generate_pytest_suite", "run_pytest_suite"]
