# Codex / MCP 客户端接入

本文件说明如何把 wensu（文溯）作为 MCP 服务接入 Codex 类客户端。目标是最小权限、
显式工具发现、无 MCP 时停止，而不是绕过风控或改用脚本直连站点。

## 1. 安装

源码安装：

```bash
pip install -e ".[dev]"
```

发行包安装：

```bash
pip install wensu
# 离线时用 Releases 里的 wheel：
pip install .\wensu-<版本>-py3-none-any.whl
```

发行包自带浏览器资源。安装后先导出：

```powershell
wensu assets --target .\browser
pwsh .\browser\native-host\install.ps1
```

`assets` 默认拒绝覆盖已有目录；升级时显式加 `--force`。

## 2. MCP 配置模板

stdio（推荐）。**Codex 用 `~/.codex/config.toml`，不是 JSON**：

```toml
[mcp_servers.wensu]
command = "wensu"
args = ["serve", "--transport", "stdio"]
```

其他客户端（Claude Desktop、Cursor 等）用 JSON：

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

HTTP（仅本机，需 bearer token）。Codex：

```toml
[mcp_servers.wensu]
url = "http://127.0.0.1:8765/mcp"
http_headers = { Authorization = "Bearer <token>" }
```

其他客户端：

```json
{
  "mcpServers": {
    "wensu": {
      "url": "http://127.0.0.1:8765/mcp",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

token 在 `%LOCALAPPDATA%\scholar-search\http-token`。

## 3. 工具发现与依赖

连接后应先调用 `status`，确认：

- `channels` 含 `cnki`；
- `bridge_ready` 为 `true`（表示至少一个宿主回应 ping，而不只是端点文件存在）；
- `cooldown_until` 为 `null`。

可用工具有五个：`search`、`detail`、`detail_many`、`export`、`status`。数量不对按安装错误处理。

**注意**：`schemas/tools.json` 是这个仓库对工具契约的**描述**，实际 `tools/list` 由 FastMCP
从函数签名自动生成，两者并不完全一致（见 `docs/reviews/wensu-acceptance-2026-11-09.md` 的 A08）。
以 `tools/list` 的实际返回为准。

运行依赖：`mcp>=1.20`、`beautifulsoup4`、`lxml`、`uvicorn`。没有浏览器侧宿主与扩展时，
MCP 服务可以启动，但 `search`/`detail` 会返回桥接错误。

## 4. 无 MCP / 工具不可用时的行为

以下情况必须停止并把原因告诉用户，不得改用脚本、curl 或直接访问站点：

- 客户端无法启动 MCP 进程；
- 工具列表为空或缺少 `search`；
- `status.bridge_ready` 为 `false`；
- 任意工具返回 `blocked`。

`blocked` 表示风控或验证页；24 小时冷却由内核持久化，不要换关键词、换实例或换客户端
绕过。

## 4.1 国内网络环境下最常见的"假故障"：代理换证

这是接入后最容易被误判成"这个 MCP 不行"的情况，单独用一节说明。

**现象**

```
search  →  sleep failed: content_not_ready
search  →  type failed: bridge.timeout
```

同时去看浏览器：知网标签页停在「隐私错误」页，错误码
`NET::ERR_CERT_COMMON_NAME_INVALID`，地址是 `kns.cnki.net`。

**根因**

系统代理（Clash、v2ray、部分杀毒软件、公司网关）对 `kns.cnki.net` 做了 TLS 中间人，
证书域名对不上，浏览器拒绝渲染页面。内容脚本只注入正常页面，错误页上什么都没有，
于是紧跟 `goto` 的第一个读/写动作就报 `content_not_ready`。

**为什么容易误判**

用 `curl` 或 PowerShell 的 `Invoke-WebRequest` 访问同一个地址会返回 `200`——这些工具不走
Windows 的系统代理设置。于是"命令行能通、MCP 报错"看起来像 MCP 的 bug，其实是两条完全不同的链路。

**处理**

让 `cnki.net` 直连，任选其一：

- 代理软件里加规则：`DOMAIN-SUFFIX,cnki.net → DIRECT`（推荐，持久且只影响知网）；
- 或加进 Windows 代理例外：

```powershell
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
$cur = (Get-ItemProperty $key).ProxyOverride
if ($cur -notmatch 'cnki\.net') {
    Set-ItemProperty $key -Name ProxyOverride -Value ($cur.TrimEnd(';') + ';*.cnki.net;cnki.net')
}
```

改完重启浏览器（或调用 `InternetSetOption(NULL, 39/37, ...)` 广播设置）。

**验证**

在同一个浏览器窗口里打开 <https://kns.cnki.net/kns8s/search>，能看到检索框即恢复。
再调一次 `status`，`bridge_ready` 应为 `true`。

**不要做的**：不要因为报错就反复重试 `search`——每次重试都在消耗配额，如果页面上恰好是验证页，
还会触发 24 小时冷却。


## 5. 技能文件

`skills/` 下三份 `SKILL.md` 可直接复制到客户端的技能目录：

- `scholar-search`：检索与专业检索式；
- `scholar-detail`：单篇详情；
- `scholar-export`：RIS/EndNote 题录。

技能中的约束与服务端一致：只读、单次一页、逐年筛选只作用当前页、遇阻即停。

## 6. 自定义 HOME

浏览器启动的宿主无法继承 shell 环境变量，因此 `install.ps1` 会把
`SCHOLAR_SEARCH_HOME` 写入 `native-host/runtime-home.txt`，宿主启动时读取该文件。
MCP 客户端一侧用 `env.SCHOLAR_SEARCH_HOME` 指向同一目录，两边才会共享配额、冷却与
桥接端点。
