# 验收清单（v0.3.6）

供独立验收使用。所有检查点都应是可复现的；与预期不符时按最后一节记录。

> 0.3.6 纳入 R035-01/R035-02 与搜索等待预算修复：类型只接受完整值或显式类型字段，\n> 支持《期刊》/（网络首发）等装饰；搜索 wait_for 预留 2s 回复余量。\n>\n> 0.3.5 修复了 R034-01：详情类型只从元数据头部读取，正文/相关推荐/摘要中的\n> “博士学位论文”“会议”等词不再覆盖当前文章类型；卷期页证据优先判定为期刊。\n>\n> 0.3.4 在 0.3.3 基础上修复了 CNKI `javascript:void(0)` 链接触发的 CSP 拦截：\n> 点击时只取消默认 javascript: 导航，站点自身事件处理仍执行。\n>\n> 0.3.3 在 0.3.2 基础上处理了 `live-functions-20261021-112247` 的 F01/F02：
> 保留页面文献类型并按类型导出；详情就绪选择器改为文章级，内层等待降到 8s。
>
> 本轮离线结果：项目 71、边界 4/4、风险回归 7/7、扩展边界 2/2、扩展风险 5/5。
> 早前 0.3.0 审计套件仍为 118/119，唯一失败项是宿主不再接受未受信任的
> `example.org` manifest（0.3.1 起的有意收紧）。

## 1. 代码与静态检查

```bash
python -m pytest -q
ruff check .
ruff format --check .
mypy --strict src
```

预期：

- 67 个项目测试通过；
- `ruff`、`ruff format --check`、`mypy` 均无输出（成功）。

沙箱环境注意：pytest 需要 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，并把 `TMP`/`TEMP` 指到可写目录，否则第三方插件或临时目录会导致超时。

## 2. 安全边界（静态审查）

| 检查点 | 预期 |
|---|---|
| 动作词汇 | 只有 `goto wait_for type click select read_html read_text scroll sleep` |
| 任意 JS 执行 | 不存在（无 `eval`、无 `executeScript` 注入任意代码） |
| 文件/下载动作 | 不存在；无 PDF/CAJ 下载 URL 或接口 |
| 域名白名单 | 由渠道 manifest 声明，内核与宿主双重校验 |
| 频率 | 硬下限 900ms（ADR 0021/0023：页内 UI 150ms）、并发 1、单页 ≤3、日 ≤300 |
| 风控 | 命中验证码/验证页/403/登录跳转即 `blocked` + 24h 冷却，无自动重试 |
| 凭据 | 仓库零 cookie、零 token、零会话数据 |

可快速核对：

```bash
grep -rn "download" src/scholar_search/channels | grep -v "downloads" || true
grep -rn "eval\|execute_script\|executeScript" src extension || true
```

## 3. 真机前置

1. `pwsh native-host/install.ps1`（注册 Edge/Chrome 原生宿主）；
2. `edge://extensions` 开发者模式加载 `extension/`，记录扩展 ID；
3. 启动 Edge（用户配置目录自定），打开任意页面；
4. 确认端点文件存在：`%TEMP%\scholar-search\bridge.json`，且 `hosts\` 下有宿主注册文件。

## 4. 功能用例

| # | 调用 | 预期 |
|---|---|---|
| T1 | `status` | `channels=["cnki"]`，`bridge_ready=true`，`cooldown_until=null` |
| T2 | `search("IPMC", limit=20)` | `total=595`，20 条，字段含 title/authors/source/year/url |
| T3 | `search("SU='IPMC' and KY='驱动器'")` | 约 57 条，全部切题 |
| T4 | `search("IPMC", page=2)` | `page=2`，标题与第 1 页不同 |
| T5 | `search("IPMC", page=4)` | 报错：`page must be <= 3` |
| T6 | `search("IPMC", limit=50)` | 50 条，`page_count=12` |
| T7 | `search("IPMC", limit=50, sort="date")` | 50 条，年份严格降序 |
| T8 | `detail(<T2 第一条 url>)` | 标题/作者/单位/DOI/摘要齐全；网络首发无卷期页 |
| T9 | `export(records=[T2 第一条], format="ris")` | 含 `TY`/`TI`/`AU`/`T2`/`PY`/`UR` |
| T10 | `search("IPMC", year_from=2025, year_to=2025)` | 仅 2025 年记录；`total` 仍为站点总数 |
| T11 | 离线：伪造 `captcha_visible=true` 的 outcome | 返回 `blocked`，写入审计，24h 冷却 |

### 印刷版卷期页（离线回放即可）

```bash
python - <<'PY'
from pathlib import Path
from scholar_search.channels.cnki.v2026_10 import get_channel
html = Path("tests/fixtures/cnki_detail_print_2026_10.html").read_text(encoding="utf-8")
r = get_channel().parse_detail(html, url="https://kns.cnki.net/x")
assert (r.year, r.volume, r.issue, r.pages) == (2022, "54", "01", "184-195")
print("ok", r.source, r.title[:20])
PY
```

## 5. 已知限制（不算缺陷）

- 单次最多 3 页；`page` 取值 1–3。
- `year_from/year_to` 是客户端筛选，只作用于本次抓取的记录。
- 站点年度控件不可用（会让结果表消失），代码不碰它。
- 网络首发文章没有卷期页，返回 `null`；印刷版才有。
- 排序每次多 2 个网格请求（复位相关度 + 点目标列）。
- 宿主进程可能并存多个（浏览器重连），适配器按 ping 选择可用者。
- 扩展的登录门选择器仍保留 `Ecp_top_login_*` 作为候选（同时有通用
  `login-modal` 候选）。审计的扩展离线脚本只用 `modals[0]` 响应所有
  `Ecp_top_login` 选择器，因此 `visible_second_login_gate_is_seen` 在该模拟器里
  无法表达“第二个弹窗可见”，9/10 通过；浏览器真实 DOM 下会遍历所有候选。

## 6. 问题记录格式

发现不符时，请记录：

1. 版本与提交：`v0.3.0`；
2. 调用参数（完整 JSON）；
3. 实际返回（脱敏后）；
4. 预期与实际差异；
5. 是否可稳定复现（连续 2 次）。




