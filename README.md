# URL2SPEC — 智能接口测试智能体

给定页面 URL，自动完成：接口抓包 → 清洗 → LLM 分析 → 接口文档 → pytest 脚本 → 测试报告。

## 项目结构（4 个核心模块）

```
URL2SPEC/
├── main.py              # 主入口
├── capture/             # 采集：Playwright 抓包、清洗、脱敏、VIP 解密
├── llm/                 # LLM 推理：提示词 + 客户端
├── report/              # 报告渲染代码：接口文档、测试报告、知识库合并
├── testing/             # 测试：脚本生成、pytest 执行、单元测试
│   ├── script_generator.py
│   ├── runner.py
│   └── unit/            # 项目 pytest 单元测试
├── test/                # 用户自定义脚本（勿放核心代码）
├── docs/                # 文档：需求说明、知识库模板、生成的接口/测试文档
└── output/              # 中间运行产物（git 忽略）
    ├── data/
    ├── reports/         # JUnit XML 等机器报告
    └── generated_tests/
```

## 快速开始

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env

python main.py "https://vip.yaozh.com"
```

### 首次登录并保存 Cookie

如果还没有 cookie 文件，直接指定一个保存路径。程序会先打开浏览器登录页，手动登录完成后回到终端按 Enter，登录态会保存到该文件；随后自动进入目标页开始采集。

```bash
python main.py "https://vip.yaozh.com" --cookie-file "./cookies.json"
```

如果登录页和目标页不同，可以额外指定登录页：

```bash
python main.py "https://vip.yaozh.com/member" \
  --cookie-file "./cookies.json" \
  --login-url "https://vip.yaozh.com/login"
```

后续再次运行同一个命令时，会优先加载 `./cookies.json`，直接绕过登录。若 cookie 过期，可强制重新登录并覆盖保存：

```bash
python main.py "https://vip.yaozh.com" --cookie-file "./cookies.json" --refresh-cookie
```

生成 pytest 接口回放测试时，也会自动复用 `--cookie-file` 中的 cookie，避免测试请求因缺少登录态变成无效 401/未登录响应。

也可以在 `.env` 中配置默认路径：

```env
CAPTURE_COOKIE_FILE=./cookies.json
CAPTURE_LOGIN_URL=https://vip.yaozh.com/login
```

加载已有文件时支持的格式：

- Playwright `storage_state.json`：`{"cookies": [...], "origins": [...]}`
- 浏览器导出的 cookie JSON 数组：`[{"name": "...", "value": "...", "domain": "...", "path": "/"}]`
- 简单 JSON 键值：`{"sid": "xxx", "token": "yyy"}`
- Cookie 请求头字符串：`sid=xxx; token=yyy`
- Netscape `cookies.txt`

### 按 URL 过滤采集接口

默认采集页面触发的全部 XHR/Fetch 接口。若只希望采集指定路径下的接口，可以使用通配符过滤：

```bash
python main.py "https://vip.yaozh.com" --url-filter "api/zgqxss/*"
```

规则会匹配接口 path，因此 `api/zgqxss/*` 可以匹配 `/api/zgqxss/list`、`/api/zgqxss/detail?id=1` 这类接口。多个规则可以重复传入：

```bash
python main.py "https://vip.yaozh.com" \
  --url-filter "api/zgqxss/*" \
  --url-filter "api/user/*"
```

也可以在 `.env` 中配置，多个规则用英文逗号分隔：

```env
CAPTURE_URL_FILTERS=api/zgqxss/*,api/user/*
```

采集阶段会按接口结构自动去重：同一路径下 query 参数值不同、JSON body 字段值不同、form body 字段值不同的请求，只保留一条接口记录；如果参数名或 body 字段结构不同，则视为不同接口。

### 固定接口知识库

每次采集和 LLM 分析完成后，会增量更新固定知识库，默认路径：

```text
docs/api_knowledge_base.json
```

真实知识库可能包含抓包样本、接口返回片段或用户数据，默认不提交到 Git；仓库中提供 `docs/api_knowledge_base.example.json` 作为结构模板。

生成的人工阅读文档默认输出到：

- `docs/api_doc.md`
- `docs/test_report.md`

这两个文件由当前采集数据生成，默认不提交到 Git；如需沉淀正式版本，可人工脱敏后另存。

知识库按 `请求方法 + 域名 + 接口路径` 合并接口，适合长期维护和人工修订。常用字段：

- `include_in_tests`：是否生成接口测试，公共接口可改为 `false`
- `test_skip_reason`：跳过测试原因，例如 `公共字典接口，无需回放测试`
- `tags`：接口标签，例如 `["common", "dict"]`
- `kb_notes`：知识库维护备注
- `locked`：设为 `true` 后后续采集不会覆盖该接口条目
- `manual_overrides`：手动覆盖 `analysis`、`source`、`raw` 中的字段

后续再次采集时，程序会先用知识库判断接口是否已处理过。已存在的接口会跳过 LLM 分析，只有新增接口才会调用 LLM；如果本次没有新增接口，则直接基于现有知识库重新生成文档和测试。

示例：公共接口只进入文档，不生成 pytest：

```json
{
  "include_in_tests": false,
  "test_skip_reason": "公共接口，无需加入接口回放测试",
  "tags": ["common"]
}
```

也可以用规则批量标记公共接口：

```bash
python main.py "https://vip.yaozh.com" --skip-test-filter "api/common/*"
```

或写到 `.env`：

```env
API_KNOWLEDGE_BASE_FILE=docs/api_knowledge_base.json
COMMON_API_FILTERS=api/common/*,api/dict/*
```

## 测试说明

| 类型 | 位置 | 命令 |
|------|------|------|
| 项目单元测试 | `testing/unit/` | `pytest` |
| 用户脚本 | `test/` | `python test/example_capture.py` |
| 流水线生成的接口测试 | `output/generated_tests/` | 由 `main.py` 自动执行 |
