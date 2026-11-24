# 文溯 · wensu

！！！  注意不要用机构或大学的IP自动化访问这些网站，可能面临来自他们的处罚  ！！！


**一句话：回答科学专业问题前，AI 会先查知网 / Web of Science、读完论文正文再作答——答案带原文出处，不瞎编。**

- **查库**：直接查知网和 Web of Science（不是搜公开网页），一次取回上百篇，先按摘要和影响因子
  筛出真正要读的几篇
- **读正文**：在你平时用的那个浏览器里打开论文，把正文整篇读完（机构订阅能读到的都能读），
  给出每节要点、关键句，以及**带原句的关键数据**
- **答得实**：AI 回答时能把这些出处摆出来，写综述、核对数据不用你再一篇篇翻

只读，不下载 PDF；遇到验证码会停下来等你处理。以下细节给技术用户和 agent。

## 和“直接联网搜一下”有什么不同

普通联网搜索能帮你找到论文的**网页**，但回答专业问题时通常不够：

| | 普通联网搜索 | 文溯 |
|---|---|---|
| 搜的地方 | 公开网页 | 知网、Web of Science **数据库本体**：专业检索式、影响因子、被引排序 |
| 一次能拿多少 | 一页搜索结果、几段摘要 | 一次上百篇（知网 150、WoS 500），先筛后读 |
| 论文正文 | 多在付费墙后，常只拿到摘要或登录页 | 用**你已登录的浏览器**打开，机构订阅能读到的都能读 |
| 拿回来的东西 | 原始网页片段，公式/表格/图注常丢 | 分节 Markdown 全文 + 文献地图（每节要点、关键句、带原句的数值） |
| 能不能核对 | 常说不清“这句出自哪” | 每个关键数值都附它所在的原句，能指回论文 |
| 会不会惹麻烦 | 硬抓容易被拦 | 遇验证码立即停下等你处理，能长期用 |

简单说：**搜索解决“找到”，文溯解决“读懂并引用”。**

> 发行名 **wensu**（中文名「文溯」）。命令是 `wensu`，旧的 `scholar-search` 保留为兼容别名；
> Python 模块名仍是 `scholar_search`，运行期目录仍是 `%LOCALAPPDATA%\scholar-search`，老配置无需改动。

> **独立项目，非官方**，与任何数据库运营方无隶属、合作或授权关系。

[![开放插件市场](https://img.shields.io/endpoint?url=https%3A%2F%2Fdshopen.org%2Fbadge%2F%40hui-xu-ai%2Fdsh-wensu.json)](https://dshopen.org/zh/plugins/@hui-xu-ai/dsh-wensu/)

## 细节（给技术用户和 agent）

万方、维普等以后按同一契约接入。

### 一条链怎么走

```text
1) 找  search(channel="webofscience", query="TS=(ionic polymer actuator) AND PY=(2024-2026)",
              records_from=1, records_to=150, min_impact_factor=6)
2) 筛  detail(url=…, include_abstract=True)          # 只读摘要，决定读哪三篇
3) 读  page_read(doi="10.1038/s41586-020-2649-2")     # → page.mhtml
       wensu page2md --in page.mhtml --out out            # → page.md + index.json（文献地图）
4) 引  export(records=…, format="ris")                # 手动导入 Zotero / EndNote
```

一条链 = 4 次工具调用。检索 1 个额度起，精读固定 2 个额度，日上限 300 由内核强制。

## 它能做什么

**找 · 检索题录**

- **关键词检索**：标题、作者、刊名、年份、被引、下载、详情链接
- **专业检索式**：知网官方 17 个字段（`SU/TKA/KY/TI/FT/AU/FI/RP/AF/FU/AB/CO/RF/CLC/LY/DOI/CF`），
  支持 `and/*`、`or/+`、`not/-`、`%` 与括号
- **记录范围**：`records_from` / `records_to` 一次读一整段（知网翻页 150 条、WoS 导出 500 条），
  不再靠"排除已读"反复重检
- **排序**：相关度 / 发表时间降序 / 被引降序；WoS 还带影响因子，可在本地筛选排序

**读 · 全文精读**（`page_read` + `wensu page2md` 子命令）

- **打开页面**：`page_read(doi=…)` 在浏览器里直接打开文章地址，存成 `<home>/pages/<slug>/page.mhtml`，
  并给出 `status`（`ok` / `no_html` / `unsupported_site` / `blocked`）与原因
- **全文 Markdown**：`page2md` 产出 `page.md`，公式、上下标、表格、图注按章节保留
- **文献地图**：`index.json` 给每节的要点、关键句、带原句上下文的数值，先看地图再决定读哪一节
- **按需切片**：`--slice 3`、`--query "μ"`、`--mode core`，只取需要的部分，省上下文
- **贯读手上那页**：`snapshot` 把你自己已经开着的页面存成 MHTML，零额度

**交 · 详情与引用**

- **单篇详情**：摘要、关键词、作者单位、卷期页、DOI
- **导出**：RIS / EndNote 纯文本，保留页面给出的文献类型（期刊 / 学位论文 / 会议 / 图书 / 报纸…）
- **状态**：`status` 看配额、冷却、桥接是否就绪

## 它不做什么

- **不绕过人机验证**：`page_read` 直接打开文章地址（等于你自己把链接粘进地址栏），不做导航预热、
  不模拟站内跳转；遇到验证页立即停机返回 `blocked`，等**你**在浏览器里点完验证再继续
- **不下载 PDF / CAJ**：精读的是**网页正文**（渲染后的文章页），不调用任何下载接口，不解包 PDF
- **不把题录写入 Zotero / EndNote / Mendeley**。只输出 RIS / EndNote 文本，
  导入由你自己在软件里完成（原因见 [ADR 0006](docs/adr/0006-no-third-party-ingest.md)）
- **不做批量抓取**，没有"爬全库"模式，日上限 300 次由内核强制
- 不实现来源类型筛选（传了会明确报错）；年份筛选只作用于本次已抓取的记录

## 安全边界

| 约束 | 值 |
|---|---|
| 动作词汇 | 固定九个：`goto` `wait_for` `type` `click` `select` `read_html` `read_text` `scroll` `sleep` |
| 任意 JS | 没有。扩展只认这九个动作，选择器由计划带下来 |
| 域名 | 白名单，由渠道 manifest 声明，内核与宿主双重校验 |
| 最小间隔 | 3000 ms 硬下限，外加 0–1.2 s 随机抖动，并发 1 |
| 单次计划 | ≤ 40 个动作 / ≤ 200 s |
| 每日配额 | 300 个网络动作（读类动作不计数） |
| 风控 | 验证页 / 验证码 / 403 / 登录跳转 → 立即终止，返回 `blocked`，冷却 24 h，不自动重试 |
| 凭证 | 零。不读也不存任何账号、Cookie、会话材料 |

## 工作原理

```
MCP 客户端 ──stdio / HTTP──▶ MCP server
                               │
                 内核：契约 / 策略 / 风控 / 计划 / 审计 / 缓存
                               │
        ┌──────────────────────┴───────────────────────┐
        │                                              │
  渠道插件 channels/                            page_read / snapshot
  cnki/、webofscience/                          （25 家出版社白名单）
  检索 · 详情 · 导出                             通读：只 goto，不点不填
        │                                              │
        └──────────────────────┬───────────────────────┘
                               │
                    桥接适配器 ──TCP(loopback+token)──▶ 原生宿主
                                                        │
                                                  stdio │ 浏览器原生消息
                                                        ▼
                                         扩展 ──▶ 你的浏览器（九个动作）
                                                        │
                                          chrome.pageCapture（分块过桥）
                                                        ▼
                      内核写盘 <home>/pages/<slug>/page.mhtml
                                                        │
                    wensu page2md ──▶ page.md + index.json（文献地图）
```

你不需要开调试端口，也不需要交出浏览器控制权。

- **检索**：扩展只做九个通用动作（`goto`/`wait_for`/`type`/`click`/`select`/`read_html`/`read_text`/
  `scroll`/`sleep`），站点知识（选择器、流程、解析）全在 Python 侧的渠道插件里。
- **通读**：内核只发导航，页面由浏览器自己渲染，`chrome.pageCapture` 分块过桥、**内核写盘**
  （不走下载管理器，否则 Edge 会留下 `.crdownload`）。之后是纯本地转换：`page2md.py` 产出
  `page.md` 与文献地图 `index.json`，不再访问任何站点。

## 快速开始

前置：Windows、Python 3.11+、Edge（或 Chrome）。浏览器侧目前只在 Windows 上提供。

```powershell
# 1) 装包（已发布到 PyPI；离线时用 Releases 里的 wheel）
pip install wensu

# 2) 一条命令装好浏览器资源与原生宿主
wensu setup

# 3) 装扩展（只需一次）：edge://extensions → 开发者模式
#    → 加载解压缩的扩展 → 选 wensu setup 打印的 extension 目录
#    扩展 ID 由 manifest 里的 key 固定，恒为 gmaimbocfjkolcpljeekjcomakipoaph

# 4) 验证
wensu status
```

`wensu setup` 把资源放到 `%LOCALAPPDATA%\scholar-search\browser`，注册 Edge/Chrome 的原生宿主，并打印
扩展目录；它不写系统目录，也不需要管理员权限。想自己指定位置或只复制资源，用
`wensu setup --target <目录>` / `wensu setup --no-host`。

`status` 里 `bridge_ready: true` 就通了。

更细的步骤（新建独立 Edge 环境、多浏览器、扩展 ID 对不上等）见
[浏览器环境与扩展](docs/browser-setup.md)。让 agent 帮你装，见
[skills/scholar-install](skills/scholar-install/SKILL.md)。

## 接入 MCP 客户端

stdio 方式（Claude Desktop、Cursor 等用 JSON 配置的客户端；Codex 用 `config.toml`，见 [Codex 接入](docs/integration/codex.md)）：

```json
{
  "mcpServers": {
    "wensu": {
      "command": "wensu",
      "args": ["serve", "--transport", "stdio"]
    }
  }
}
```

HTTP 方式（本地回环 + 令牌）：

```bash
wensu serve --transport http --host 127.0.0.1 --port 8765
```

令牌在首次启动时写入 `%LOCALAPPDATA%\scholar-search\http-token`，请求带
`Authorization: Bearer <token>`，端点 `http://127.0.0.1:8765/mcp`。
细节见 [docs/integration/dsh.md](docs/integration/dsh.md)。

## 工具

| 工具 | 参数 | 返回 |
|---|---|---|
| `search` | `query`（关键词或专业检索式）、`channel`、`page` 1–3、`limit` 1–50、`records_from`/`records_to`、`sort`、`year_from`/`year_to`、`fields`、`count_only` | `total`、`page`、`page_count`、`records[]`、`quota_charged` |
| `detail` | `url`（`search` 返回的链接或裸 DOI）、`channel`、`include_abstract`、`fields` | 单条完整题录（含摘要、DOI、卷期页） |
| `detail_many` | `urls[]`、`include_abstract`、`fields` | `results[]`、`ok_count`、`failed_count`；遇风控整批停止 |
| `export` | `records`、`format`：`ris`/`endnote`/`markdown`/`csv`、`out_path` | 纯文本；给了 `out_path` 则写盘且不回传正文 |
| `page_read` | `doi`（优先）或 `url` | **2 单位**：直接打开文章地址并抓取为 MHTML，回报 `status`（`ok`/`no_html`/`unsupported_site`/`blocked`）、`mhtml_path`、`reason`、`pdf_url`、`quota_charged` |
| `snapshot` | — （只作用于当前标签页） | **0 单位**：把用户正开着的页面存成 MHTML；遇人机验证返回 `blocked`/`RISK_CAPTCHA` |
| `status` | `brief` | 渠道、剩余配额、冷却状态、桥接是否就绪 |

`include_abstract` 默认 **false**，`fields` 可把响应压到只留需要的键（`url` 与额度字段总是保留）。

**检索后的详情不一定免费**：WoS 的列表抓取会播种完整详情，`detail` 命中缓存扣 0；**知网的列表
不播种详情**，第一次 `detail` 需要一次网络动作，扣 1。同一篇再取则扣 0。

`search` 的年份筛选是**客户端筛选**：只对本次抓到的那一页生效，`total` 仍是站点总数。
筛选后为空说明目标年份不在这一页，换页或换检索式，不要连续翻页扫库。

**想多读几条，用记录范围，不要用排除法**（[ADR 0020](docs/adr/0020-record-range-export.md)）：
两个渠道都吃 `records_from` / `records_to`，机制不同、效果一样——知网靠**翻页**（一次最多三页
= 150 条），WoS 全球站靠**站点导出**（一次 500 条）。

```text
search(query="TS=(ionic actuator*)", channel="webofscience", records_from=1,   records_to=500)
search(query="TS=(ionic actuator*)", channel="webofscience", records_from=501, records_to=1000)

search(query="钙钛矿太阳能电池", channel="cnki", records_from=1,   records_to=150)
search(query="钙钛矿太阳能电池", channel="cnki", records_from=151, records_to=300)
```

- 一次调用读一整段：WoS **500 条**（以前 500 条要 10 次检索）、知网 **150 条**（以前 3 次检索）；
- 上限来自站点与交互纪律：WoS 站点允许 1000，但更大的导出赶不上单动作 15 秒的下载等待（实测）；
  知网每页 50 条、单次最多 3 页，所以 150；
- **知网的范围必须从第 1 条开始**（它是翻页，不跳到第 11 页）：`records_from` 只能是 1；
- 范围**超过实际结果集**时返回实际条数（例如只有 9 条命中就回 9 条），不报错；
- `records_from/records_to` 与 `page` 互斥；
- WoS 的范围读 `total` 是 `null`（导出文件只说带了多少条）；知网的 `total` 仍是站点命中数；
- `exclude_ut` 仍然可用，但用途已经收窄成“隐藏我手上已有的记录”，不再用来深入。

## 并发

**一个浏览器 profile 同一时间只应服务一个 agent。**

同一 profile 下的检索与详情由同一把跨进程事务锁串行化：一条检索从提交到读取期间持有整把锁，
`detail` 和 `journal` 也拿同一把，所以它们不会插进检索的中途。后到的请求**排队等待**，不会读到
别人的页面。

多个 profile 时，每个浏览器有自己的 host。host 无法报告自己属于哪个 profile——它读的是同一份
`browser.json`——所以当有**多个 host 且它们声称同一个 profile** 时，工具会拒绝连接并说明原因，
而不是随机挑一个。目前可行的多 profile 用法是：一个 profile 一个 host，用 `WENSU_PROFILE`
指定本次调用使用哪个；无法消歧时请关掉多余浏览器。

## 升级到新版本

```powershell
pip install --upgrade wensu
wensu setup            # 刷新资源副本 + 重写宿主清单与注册表项
# 重启 MCP 客户端，让它重新拉起 server 进程
```

要点：

- **必须重启 MCP 客户端**。server 是 stdio 子进程，模块在启动时导入，换文件不会热生效。
- **`wensu setup` 自己判断要不要刷新**：复制出去的资源与 wheel 里的一致时它什么都不做
  （打印 `already matches this build`），不一致就替换并提示重载扩展——**这一步不需要 `--force`**。
  过去不带 `--force` 会直接跳过并仍然返回 0，于是副本停在旧版本而没人发现。
- 扩展**通常不用重装**：Python 侧改动不影响扩展；只有 `extension/` 里的 JS 或
  `manifest.json` 变了才需要重新加载扩展。重载后 `wensu status` 里
  `browser_profile.extension_version_mismatch` 应为 `false`。
- **两个 `--force` 分开了**：`--force-assets` 连「内容相同」的副本也重刷（文件可疑时用）；
  `--force-skills` 替换已存在的技能目录，**会删掉你对 `SKILL.md` 的本地修改**。不加 `--force-skills` 时，
  `setup` 只报告「N 个技能与本版本不同」，不擅自覆盖。
- **`--force` 不再动浏览器配置**。如果你用 `wensu browser adopt` 指定过专用 profile，升级后它仍然有效。
  要连浏览器配置一起重置，用 `--reset-browser`——这会把 `browser.json` 换成默认的
  `profiles/edge`，原来的窗口和已经装好的扩展不会跟着迁移。

完整流程、目录布局与回滚见 [docs/operations.md](docs/operations.md)。

## 状态

当前版本见 `wensu --version`（`pip install wensu` 即可，PyPI 与 GitHub Release 同步）。真机验证过的能力：

| 能力 | 状态 |
|---|---|
| 知网关键词检索 | 通过（`IPMC` 595 条、`钙钛矿太阳能电池` 11820 条） |
| 知网专业检索式 | 通过（`SU='IPMC' and KY='驱动器'`） |
| 知网翻页 1–3 | 通过 |
| 知网每页 50 条 | 通过 |
| 知网排序（时间 / 被引） | 通过，稳定降序 |
| 知网单篇详情 | 通过（含摘要、作者单位、卷期页） |
| 导出 RIS / EndNote | 通过（图书 → `TY  - BOOK`，学位论文 → `THES`） |
| **WoS 关键词检索** | 通过（`actuator` 63025 条，单次取 50 条约 23 秒） |
| **WoS 专业检索式** | 通过（`TS=(ionic AND (soft OR flexible) AND actuator) AND PY=(2026)`） |
| **WoS 翻页第 2 页** | 通过（50 条，与第 1 页无重叠） |
| **WoS 影响因子** | 通过（记录自带 `impact_factor`，本地筛选/排序零请求） |
| **WoS 摘要按需取** | 通过（检索时播种缓存，`detail` 零网络动作） |
| **文献通读 `page_read`** | 通过（Nature `10.1038/s41586-020-2649-2` → `ok`；遇到人机校验 → `blocked`/`challenge`，不重试、不绕过） |
| **文献地图 `wensu page2md`** | 通过（`page.md` 全文 + `index.json` 地图，约原文体积的 45%，验收 9/10） |

## 检索失败了？先看这三条

**这个 MCP 报告"检索失败"时，九成不是 MCP 的问题，而是浏览器或网络环境。** 按下面的顺序排查，
不要反复重试（重试只会消耗配额，遇到风控还会触发 24 小时冷却）。

### 1. 代理软件对知网做了 TLS 中间人（国内最常见）

**现象**：`search` 返回 `sleep failed: content_not_ready` 或 `type failed: bridge.timeout`；
去看浏览器，窗口标题是「隐私错误」，页面上写着
`NET::ERR_CERT_COMMON_NAME_INVALID`，地址是 `kns.cnki.net`。

**原因**：Clash / v2ray / 其他系统代理把 `kns.cnki.net` 的证书换成了自己的，证书名对不上，
浏览器拒绝加载，页面变成错误页——错误页上没有人注入内容脚本，动作自然全部失败。

**容易误判的地方**：用 PowerShell 的 `Invoke-WebRequest` 或 curl 访问同一个地址会返回 200，
因为命令行工具不走系统代理设置。于是很容易得出"网站是好的，是 MCP 坏了"的结论——恰恰相反。

**处理**：让 `cnki.net` 直连。任选其一：

```text
# 在代理软件里加规则（推荐，持久）
DOMAIN-SUFFIX,cnki.net → DIRECT
```

```powershell
# 或者把它加进 Windows 的代理例外，然后重启浏览器
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
$cur = (Get-ItemProperty $key).ProxyOverride
if ($cur -notmatch 'cnki\.net') {
    Set-ItemProperty $key -Name ProxyOverride -Value ($cur.TrimEnd(';') + ';*.cnki.net;cnki.net')
}
```

**验证**：在那个浏览器窗口里打开 <https://kns.cnki.net/kns8s/search>，能看到检索框就对了。

### 2. 全新浏览器环境被要求人工验证

新 profile 没有 Cookie 与访问历史，第一次检索多半会落到知网的「安全验证」页，工具会正确返回
`blocked` 并上 24 小时冷却。这不是故障：在那个窗口里人工过验证，然后
`wensu reset --confirm`，再检索一次。详见
[浏览器环境](docs/browser-setup.md#61-全新环境第一次访问几乎一定会遇到安全验证)。

### 3. 窗口不在前台，定时器被节流

浏览器把后台窗口的定时器按整秒分桶，暂停动作会迟到，表现为 `bridge.timeout` 且
`duration_ms` 贴着超时值。把知网窗口切到前台、只留一个可见窗口再试。

更多排障（宿主没起来、`goto` 超时、配额用尽等）见[运维手册](docs/operations.md#7-排障)。

### 4. 出版社页面要求人机验证

`page_read` 打开的是**普通的文章地址**，和你在浏览器里粘贴链接没有区别。如果站点判定这个环境可疑，
它会返回验证页；工具此时给出 `blocked` / `challenge`（附 `signal`，例如命中的标记词）并立即停止，
**不重试、不换 IP、不尝试识别验证码**（[ADR 0004](docs/adr/0004-stop-on-challenge.md)）。处理办法只有一个：

1. 在那个浏览器窗口里**人工**完成验证（拖动滑块 / 点选），确认文章正文能正常显示；
2. 再调一次 `page_read`。

连续对同一个站点高频调用会更容易触发这一步，所以按需读、不要批量刷。

## 目录

```
src/scholar_search/core/       内核：契约、注册表、策略、风控、审计、缓存、导出
src/scholar_search/channels/   渠道插件（cnki/2026.10、webofscience/2026.11）
src/scholar_search/adapters/   浏览器适配器（bridge 生产 / fixture 测试）
src/scholar_search/transports/ stdio 与 HTTP
native-host/                   原生消息宿主（纯通讯层，Windows）
extension/                     浏览器扩展（九个动作，零站点知识）
tools/                         文献通读：page2md.py（MHTML → Markdown + 文献地图）
schemas/                       记录与工具 JSON Schema
skills/                        给 agent 的技能说明
docs/                          架构、ADR、协议、运维、接入说明
tests/                         单元 + 契约 + fixture 回放
```

## 文档

| 文档 | 内容 |
|---|---|
| [架构说明](docs/architecture.md) | 分层、请求流、策略与风控、扩展点 |
| [运维手册](docs/operations.md) | 目录布局、部署、升级、回滚、排障 |
| [知网改版应对](docs/cnki-maintenance.md) | 站点变了改哪里、怎么验证 |
| [浏览器环境](docs/browser-setup.md) | 新建独立 Edge 环境、装扩展、扩展 ID |
| [Zotero 接入](docs/integration/zotero.md) | 手动导入 RIS 的步骤（不做自动化） |
| [发布到 GitHub](docs/publishing.md) | 推送、tag、CI 与发布 |
| [渠道契约](docs/channel-contract.md) | 新增渠道要实现的接口 |
| [WoS 渠道](docs/wos-channel.md) | 字段映射、导出、记录范围 |
| [记录范围（ADR 0020）](docs/adr/0020-record-range-export.md) | 一次读一整段：导出区间与翻页两种机制 |
| [桥接协议](docs/bridge-protocol.md) | 宿主与扩展的帧格式与校验 |
| [ADR 索引](docs/adr/) | 关键决策记录 |
| [故障台账](docs/incidents.md) | 线上踩过的坑与结论 |

## 合规声明

本项目仅用于个人学术研究中的题录检索。使用者应遵守目标站点的服务条款与所在机构的
使用规定。项目本身不附带任何数据、凭证或会话材料，也不提供把数据灌入第三方系统的能力。

## 来源与致谢

本仓库的代码是为本项目独立编写的，**没有复制任何外部项目的源码文件、模块或函数**。
沿用的只有三样：知网页面的 CSS 选择器字符串（属于 DOM 事实）、交互步骤的先后顺序
（由站点决定）、以及已知坑的知识（例如常驻隐藏的验证码 DOM）。这些做法受到三个公开的
MIT 项目启发：

- [cookjohn/cnki-skills](https://github.com/cookjohn/cnki-skills)
- [SepineTam/cnki-mcp](https://github.com/SepineTam/cnki-mcp)
- [wuruiqi/cnki-mcp](https://github.com/wuruiqi/cnki-mcp)

浏览器通道、微内核结构、策略/风控引擎、解析器与导出层都是本项目自己的设计，与它们不同
（对照见 [借鉴对照表](docs/reference-parity.md)）。完整的来源声明、依赖许可与
fixture 脱敏说明见 [NOTICE](NOTICE)。

`tests/fixtures/` 下的页面快照已脱敏：摘要、作者、单位、关键词全部替换为合成占位文本，
邮箱与会话参数已删除，只保留标记结构、类名和公开的题录事实（标题、刊名、卷期页、DOI）。

## License

MIT，见 [LICENSE](LICENSE)。
