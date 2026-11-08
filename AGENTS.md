# AGENTS.md · 项目硬约束

本文件是给所有在此仓库工作的 agent 的硬性约束。与代码注释冲突时，以本文件为准。

## 不可协商

1. **只读**：不实现、不调用任何 PDF/CAJ 下载接口。允许 RIS/EndNote 题录文本导出。
2. **不做第三方题录入库**：不实现把题录写入 Zotero、EndNote、Mendeley 等参考文献库的任何接口、
   桥接或自动化（包括本地 HTTP 端点、库文件改写、数据库直写）。只输出纯文本 RIS/EndNote，
   导入由用户自己在对应软件里完成。理由见 ADR 0006：自动入库会越过本站的服务条款边界，
   并把第三方软件的账号与库文件卷进本项目的责任范围。
3. **遇风控即停**：检测到验证码、`/verify/home`、403、登录重定向，立即终止当前计划，返回 `blocked`，写审计，冷却 24 小时。禁止自动重试、禁止更换 IP、禁止延时后重试。
4. **不破解验证码**：任何形式的自动识别、打码、绕过都不允许。
5. **频率硬下限**：最小间隔 3000ms、并发 1、单次 ≤3 页、每日 ≤300 次（ADR 0005）。这些值原则上只能收紧；放宽必须新增 ADR。
6. **动作词汇封闭**：`goto` `wait_for` `type` `click` `select` `read_html` `read_text` `scroll` `sleep`。新增动词需 ADR 并同步 host 与扩展。
7. **域名白名单**：由渠道 manifest 声明，内核与 host 双重校验。

## 开发规范

- Python 3.11+，类型全标注，`mypy --strict` 通过。
- `ruff` 格式化与检查，提交前跑 `pre-commit`。
- Conventional Commits：`feat:` `fix:` `docs:` `refactor:` `test:` `chore:`。
- 新增渠道 = 新增 `channels/<name>/<site_version>/` + `manifest.json`，不改内核。
- 解析逻辑必须有 fixture 回放测试，禁止只靠线上验证。
- 运行期数据只写 `SCHOLAR_SEARCH_HOME`（默认 `%LOCALAPPDATA%\scholar-search`），不得写入仓库。

## 隐私

- 不记录 Cookie、账号、完整 HTML。
- 审计日志只记动作、渠道、耗时、结果数、错误码、风控信号。
- fixture 必须脱敏；仓库零凭证。

## 发布

- `main` 分支保护，tag 触发发布。
- **四个发行物共用一个版本号**（ADR 0013）：Python 包、浏览器扩展、native host、DSH bundle。
  版本号写五处——`pyproject.toml`、`src/scholar_search/__init__.py`、`extension/manifest.json`、
  `packages/dsh-wensu/package.json`、`NOTICE`——由 `scripts/check-versions.py` 校验，CI 会拦。
- **发版前必须跑 `python scripts/release-check.py` 并全绿**。它覆盖版本一致、CHANGELOG 条目、
  测试、lint、类型、两层计划校验、wheel 是否装得下两个渠道。
- 版本号、CHANGELOG、NOTICE 三者必须同步。
- 完整流程见 `docs/publishing.md`；版本与契约的关系见 `docs/compatibility.md`。

