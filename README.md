# URL2SPEC

给定一个页面 URL，自动完成接口采集、LLM 分析、接口文档生成、pytest 回放测试和测试报告输出。

## 快速开始

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env

python main.py "https://vip.yaozh.com"
```

首次运行时，如果本地没有登录态，程序会打开浏览器让你登录；登录后按 Enter 或关闭页面，登录态会自动保存到 `config/<域名>.storage_state.json`。后续运行会默认复用该文件，不需要再传 `--cookie-file`。

## 常用命令

```bash
# 采集页面接口，并基于知识库增量分析
python main.py "https://vip.yaozh.com"

# cookie 过期时重新登录并覆盖本地登录态
python main.py "https://vip.yaozh.com" --refresh-cookie

# 登录页和目标页不一致时
python main.py "https://vip.yaozh.com/member" --login-url "https://vip.yaozh.com/login"

# 只采集指定路径下的接口
python main.py "https://vip.yaozh.com" --url-filter "api/zgqxss/*"

# 忽略旧知识库，本次接口全部重新分析并覆盖知识库
python main.py "https://vip.yaozh.com" --rebuild-kb
```

多个过滤规则可以重复传入，也可以写到 `.env`：

```env
CAPTURE_URL_FILTERS=api/zgqxss/*,api/user/*
COMMON_API_FILTERS=api/common/*,api/dict/*
```

## 输出位置

| 内容 | 路径 | 说明 |
|------|------|------|
| 本地登录态 | `config/*.storage_state.json` | 私有文件，Git 忽略 |
| 接口知识库 | `docs/api_knowledge_base.json` | 长期维护，默认 Git 忽略 |
| 接口文档 | `docs/api_doc.md` | 由当前知识库生成 |
| 测试报告 | `docs/test_report.md` | 由本次 pytest 结果生成 |
| 原始/清洗数据 | `output/data/` | 临时运行产物 |
| 生成的 pytest | `output/generated_tests/` | 临时运行产物 |
| JUnit XML | `output/reports/` | 临时运行产物 |

## 项目结构

```text
URL2SPEC/
├── main.py              # 主入口
├── capture/             # Playwright 采集、过滤、去重、脱敏
├── llm/                 # LLM 客户端和提示词
├── report/              # 接口文档、测试报告、知识库合并
├── testing/             # pytest 脚本生成、执行器、单元测试
├── config/              # 本地私有配置和登录态
├── docs/                # 知识库模板、生成文档
└── output/              # 运行中间产物
```

## 知识库维护

知识库默认是增量模式：已经存在的接口不会重复调用 LLM，只有新增接口会分析。接口按 `请求方法 + 域名 + 路径` 合并。

常用维护字段：

| 字段 | 用途 |
|------|------|
| `include_in_tests` | 是否生成 pytest 回放测试 |
| `test_skip_reason` | 不测试的原因 |
| `tags` | 标签，如 `common`、`core`、`auth` |
| `kb_notes` | 人工维护备注 |
| `locked` | 锁定后后续采集不覆盖该接口 |
| `manual_overrides` | 手动覆盖分析结果 |

公共/低价值接口会被自动标记为不测试，例如 `api/config/*`、`api/search/config`、`api/ad`、`api/synclogin/*`、`resources/*`。

默认规则在 `report/knowledge_base.py` 的 `COMMON_API_PATTERNS` 中维护。需要新增公共接口规则时，追加一条：

```python
COMMON_API_PATTERNS = (
    ("api/config/*", "公共配置接口，无需加入接口回放测试", ["common", "config"]),
    ("api/search/config", "搜索配置接口，无需加入接口回放测试", ["common", "config"]),
    ("api/ad", "广告接口，无需加入接口回放测试", ["common", "ad"]),
    ("api/synclogin/*", "登录同步接口依赖会话/签名，回放测试不稳定", ["common", "auth"]),
    ("resources/*", "静态资源接口，无需加入接口回放测试", ["common", "static"]),
)
```

如果某个接口需要长期纳入测试，手动改成：

```json
{
  "include_in_tests": true,
  "test_skip_reason": "",
  "tags": ["core"]
}
```

如果某个接口只进入文档、不做回放测试：

```json
{
  "include_in_tests": false,
  "test_skip_reason": "公共接口，无需加入接口回放测试",
  "tags": ["common"]
}
```

## 测试说明

```bash
pytest
```

主流程会自动生成并执行接口回放测试。每个接口通常生成两个 pytest 用例：一个正例，一个缺参负例；因此 pytest 收集数量可能是接口数量的两倍。
