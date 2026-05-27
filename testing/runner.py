"""执行自动生成的 pytest 套件并产出 JUnit 结果。"""

import subprocess
import sys
from pathlib import Path


def run_pytest_suite(tests_dir, output_dir):
    """运行 pytest 并生成 JUnit XML。

    Args:
        tests_dir: 测试目录。
        output_dir: 报告输出目录。

    Returns:
        元组 ``(exit_code, junit_xml_path, stdout, stderr)``。
    """
    tests_path = Path(tests_dir)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    junit_xml = out_path / "test_results.xml"

    if not (tests_path / "test_generated_api.py").is_file():
        return 0, str(junit_xml), "", "未生成任何可执行测试用例"

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(tests_path),
        "-v",
        "--tb=short",
        f"--junitxml={junit_xml}",
    ]

    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    return completed.returncode, str(junit_xml), completed.stdout, completed.stderr
