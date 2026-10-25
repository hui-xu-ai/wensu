# 文溯 · wensu

只读的中文文献题录检索服务，以 MCP 工具的形式提供给 AI 客户端。微内核 + 渠道插件：
知网是第一个渠道，万方、维普等以后按同一契约接入。

> 发行名 **wensu**（中文名「文溯」）。命令是 `wensu`，旧的 `scholar-search` 保留为兼容别名；
> Python 模块名仍是 `scholar_search`，运行期目录仍是 `%LOCALAPPDATA%\scholar-search`，老配置无需改动。

> **独立项目，非官方**，与任何数据库运营方无隶属、合作或授权关系。

[![开放插件市场](https://img.shields.io/endpoint?url=https%3A%2F%2Fdshopen.org%2Fbadge%2F%40hui-xu-ai%2Fdsh-wensu.json)](https://dshopen.org/zh/plugins/@hui-xu-ai/dsh-wensu/)

## 它能做什么

- **关键词检索**：标题、作者、刊名、年份、被引、下载、详情链接
- **专业检索式**：知网官方 17 个字段（`SU/TKA/KY/TI/FT/AU/FI/RP/AF/FU/AB/CO/RF/CLC/LY/DOI/CF`），
  支持 `and/*`、`or/+`、`not/-`、`%` 与括号
- **翻页**：每次 1 页，页码 1–3；每页 20 或 50 条
- **排序**：相关度 / 发表时间降序 / 被引降序
- **单篇详情**：摘要、关键词、作者单位、卷期页、DOI
- **导出**：RIS / EndNote 纯文本，保留页面给出的文献类型（期刊 / 学位论文 / 会议 / 图书 / 报纸…）

## 它不做什么

- **不下载 PDF / CAJ**，不调用任何下载接口，不碰全文
- **不把题录写入 Zotero / EndNote / Mendeley**。只输出 RIS / EndNote 文本，
  导入由你自己在软件里完成（原因见 [ADR 0006](docs/adr/0006-no-third-party-ingest.md)）
- **不破解验证码**，遇到验证页立即停机，等你人工处理
- **不做批量抓取**，没有"爬全库"模式，日上限 300 次由内核强制
- 不实现来源类型筛选（传了会明确报错）；年份筛选只作用于本次已抓取的记录

## 安全边界

| 约束 | 值 |
|---|---|
| 动作词汇 | 固定九个：`goto` `wait_for` `type` `click` `select` `read_html` `read_text` `scroll` `sleep` |
| 任意 JS | 没有。扩展只认这九个动作，选择器由计划带下来 |
| 域名 | 白名单，由渠道 manifest 声明，内核与宿主双重校验 |
| 最小间隔 | 3000 ms 硬下限，外加 0–1.2 s 随机抖动，并发 1 |
| 单次计划 | ≤ 40 个动作 / ≤ 120 s |
| 每日配额 | 300 个网络动作（读类动作不计数） |
| 风控 | 验证页 / 验证码 / 403 / 登录跳转 → 立即终止，返回 `blocked`，冷却 24 h，不自动重试 |
| 凭证 | 零。不读也不存任何账号、Cookie、会话材料 |

## 工作原理

```
MCP 客户端 ──stdio / HTTP──▶ MCP server
                               │
                        内核：契约 / 策略 / 风控 / 计划 / 审计 / 缓存
                               │
                        渠道插件 channels/cnki/v2026_10
                               │
                     桥接适配器 ──TCP(loopback+token)──▶ 原生宿主
                                                          │
                                                    stdio │ 浏览器原生消息
                                                          ▼
                                                       扩展 ──▶ 你的浏览器
```

你不需要开调试端口，也不需要交出浏览器控制权：扩展只做九个通用动作，
站点知识（选择器、流程、解析）全部在 Python 侧的渠道插件里。

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
| `search` | `query`（关键词或专业检索式）、`channel`、`page` 1–3、`limit` 1–50、`sort`、`year_from`/`year_to` | `total`、`page`、`page_count`、`records[]` |
| `detail` | `url`（`search` 返回的链接）、`channel` | 单条完整题录（含摘要、DOI、卷期页） |
| `export` | `records`、`format`：`ris` 或 `endnote` | 纯文本，不落盘 |
| `status` | 无 | 渠道、剩余配额、冷却状态、桥接是否就绪 |

`search` 的年份筛选是**客户端筛选**：只对本次抓到的那一页生效，`total` 仍是站点总数。
筛选后为空说明目标年份不在这一页，换页或换检索式，不要连续翻页扫库。

## 升级到新版本

```powershell
pip install --upgrade wensu
wensu setup --force
# 重启 MCP 客户端，让它重新拉起 server 进程
```

要点：

- **必须重启 MCP 客户端**。server 是 stdio 子进程，模块在启动时导入，换文件不会热生效。
- 扩展**通常不用重装**：Python 侧改动不影响扩展；只有 `extension/` 里的 JS 或
  `manifest.json` 变了才需要重新加载扩展。
- 原生宿主在升级后要重跑 `wensu setup --force`（它负责写清单、注册表项和低完整性标签）。

完整流程、目录布局与回滚见 [docs/operations.md](docs/operations.md)。

## 状态

当前版本 **v0.4.2**（最新 release 见仓库 Releases 页）。真机验证过的能力（2026-10-21，知网 2026.10 版页面）：

| 能力 | 状态 |
|---|---|
| 关键词检索 | 通过（`IPMC` 595 条、`钙钛矿太阳能电池` 11820 条） |
| 专业检索式 | 通过（`SU='IPMC' and KY='驱动器'`） |
| 翻页 1–3 | 通过 |
| 每页 50 条 | 通过 |
| 排序（时间 / 被引） | 通过，稳定降序 |
| 单篇详情 | 通过（含摘要、作者单位、卷期页） |
| 导出 RIS / EndNote | 通过（图书 → `TY  - BOOK`，学位论文 → `THES`） |

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

## 目录

```
src/scholar_search/core/       内核：契约、注册表、策略、风控、审计、缓存、导出
src/scholar_search/channels/   渠道插件（当前只有 cnki/2026.10）
src/scholar_search/adapters/   浏览器适配器（bridge 生产 / fixture 测试）
src/scholar_search/transports/ stdio 与 HTTP
native-host/                   原生消息宿主（纯通讯层，Windows）
extension/                     浏览器扩展（九个动作，零站点知识）
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
