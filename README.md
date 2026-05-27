# URL2SPEC — 智能接口测试智能体

给定页面 URL，自动完成：接口抓包 → 清洗 → LLM 分析 → 接口文档 → pytest 脚本 → 测试报告。

## 项目结构（4 个核心模块）

```
URL2SPEC/
├── main.py              # 主入口
├── capture/             # 采集：Playwright 抓包、清洗、脱敏、VIP 解密
├── llm/                 # LLM 推理：提示词 + 客户端
├── report/              # 报告：接口文档 Markdown、测试报告 Markdown
├── testing/             # 测试：脚本生成、pytest 执行、单元测试
│   ├── script_generator.py
│   ├── runner.py
│   └── unit/            # 项目 pytest 单元测试
├── test/                # 用户自定义脚本（勿放核心代码）
├── docs/
└── output/              # 运行产物（git 忽略）
    ├── data/
    ├── reports/
    └── generated_tests/
```

## 快速开始

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env

python main.py "https://vip.yaozh.com"
```

## 测试说明

| 类型 | 位置 | 命令 |
|------|------|------|
| 项目单元测试 | `testing/unit/` | `pytest` |
| 用户脚本 | `test/` | `python test/example_capture.py` |
| 流水线生成的接口测试 | `output/generated_tests/` | 由 `main.py` 自动执行 |
