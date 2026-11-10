---
name: scholar-install
description: 在 Windows 上安装、升级或卸载 wensu（文溯，Python 包 + 原生消息宿主 + 浏览器扩展），并验证 MCP 桥接是否可用。当用户说"装上/升级/重装这个检索服务"，或 status 里 bridge_ready 为 false 时使用。
---

# 安装 wensu（文溯）

## 何时使用

- 用户要在新机器上装 wensu；
- 用户要升级到新版本；
- `wensu status` 里 `bridge_ready: false`，需要重建宿主与扩展的链路；
- 用户换了浏览器环境（新 profile、换 Edge/Chrome）。

## 前提（先检查，别急着装）

| 项 | 检查命令 | 不满足时 |
|---|---|---|
| Windows | `$env:OS` 为 `Windows_NT` | 浏览器侧目前只支持 Windows；告诉用户 Python 侧可装，但桥接不可用 |
| Python ≥3.11 | `python --version` | 让用户装 Python，或指定解释器路径 |
| Edge 或 Chrome | `(Get-Command msedge -ErrorAction SilentlyContinue).Source` | 让用户先装浏览器 |
| 能直连知网 | `curl.exe -I https://kns.cnki.net/kns8s/search` | 代理导致证书错误时先修代理（见"失败处理"） |

## 允许 agent 做 / 必须用户做

- **agent 可以做**：建 venv、装包、导出资源、跑 `install.ps1`、改 MCP 配置、跑 `status`。
- **必须用户做**：在 `edge://extensions` 里点"加载解压缩的扩展"、把扩展 ID 告诉 agent。
  agent 没有可靠的浏览器 UI 控制手段，不要假装能代点。

## 步骤

### 1. 选定版本与目录

```powershell
$ver  = '<版本>'                                   # 与用户确认；例如 0.3.18
$root = "$env:LOCALAPPDATA\scholar-search\installations\$ver"
```

升级时不要复用正在跑的目录：先 `Copy-Item` 当前目录到新版本目录，再在新目录里换包。

### 2. 装 Python 包

```powershell
# 新装
python -m venv "$root\venv"
& "$root\venv\Scripts\python.exe" -m pip install --upgrade pip
& "$root\venv\Scripts\python.exe" -m pip install .\dist\wensu-$ver-py3-none-any.whl

# 验证
& "$root\venv\Scripts\python.exe" -m scholar_search.cli --version   # 应输出 wensu <ver>
```

### 3. 导出浏览器资源

```powershell
& "$root\venv\Scripts\python.exe" -m scholar_search.cli assets --target "$root\browser" --force
```

期望 `$root\browser\` 下出现 `native-host\`、`extension\`、`schemas\`。

### 4. 注册原生宿主

```powershell
pwsh "$root\browser\native-host\install.ps1" -Python "$root\venv\Scripts\python.exe"
```

期望输出 `registered com.scholar.search`，并打印 manifest 与 launcher 路径。
这一步会写 HKCU 注册表、生成 `scholar-host.exe`，并把 `host\` 目录标为低完整性可写。

### 5. 装扩展（交给用户）

让用户：

1. 打开 `edge://extensions`（或 `chrome://extensions`）；
2. 打开右上角"开发者模式"；
3. 点"加载解压缩的扩展"，选择 `$root\browser\extension`；
4. 把卡片上的扩展 ID 告诉 agent。

扩展 ID 由 `manifest.json` 里的 `key` 固定，正常恒为：

```
gmaimbocfjkolcpljeekjcomakipoaph
```

如果用户报的 ID 与这个不同（改过 key、或自己重新打包过），**必须**重新注册：

```powershell
pwsh "$root\browser\native-host\install.ps1" -Python "$root\venv\Scripts\python.exe" -ExtensionId "<用户给的ID>"
```

### 6. 验证

```powershell
$env:SCHOLAR_SEARCH_HOME = "$env:LOCALAPPDATA\scholar-search"
& "$root\venv\Scripts\python.exe" -m scholar_search.cli status
```

通过标准：

```json
{ "channels": ["cnki"], "cooldown_until": null, "quota_remaining": <数字>, "bridge_ready": true }
```

`bridge_ready: true` 才算装完。此时让用户开一个知网页面、把窗口留在前台。

### 7. 接 MCP 客户端（按需）

stdio 配置：

```json
{
  "mcpServers": {
    "wensu": {
      "command": "C:\\Users\\<用户>\\AppData\\Local\\scholar-search\\installations\\<版本>\\venv\\Scripts\\python.exe",
      "args": ["-m", "scholar_search.cli", "serve", "--transport", "stdio"]
    }
  }
}
```

如果客户端是 Codex，改 `~/.codex/config.toml` 的 `[mcp_servers.wensu]`；
如果是 DSH，改 bundle 的 `cordis.patch.yml`（不要手改 profile）。改完**重启客户端**，
stdio server 是子进程，不重启不会换代码。

### 7b. 装完必须重连，否则你看到的是旧工具

**磁盘上的版本换了，正在跑的会话不会自动换。** 已经打开的聊天里，工具说明和参数
schema 还是连接建立时那一份——表现出来就是「新版本有的参数，当前会话看不到」。

装完做两件事：

1. **重连 MCP**：重启客户端，或在客户端的 MCP 面板里重连 `wensu`；
2. **核对版本，而不是猜**：

```powershell
wensu --version                 # 磁盘上的
# MCP 侧：调用 status，看 version 字段
```

两边一致才说明会话已经用上新代码。不一致时不要怀疑「没装好」——
先重连，这是客户端连接生命周期的问题。

**这一条同样适用于验收报告**：报告里出现的工具 schema 若与磁盘版本不符，
先确认会话是否重连过，再判断是不是包的缺陷。

### 8. 可选：跑一次真实检索

只有用户明确同意才跑，**一次 `search` 花 3 个网络动作**，日上限 300：

```powershell
# 用 MCP 工具 search(query="IPMC", limit=3) 即可，不要用命令行拼计划
```

## 失败处理

| 现象 | 原因 | 处理 |
|---|---|---|
| `bridge_ready: false`，`host.log` 没有新的 `start` | 扩展没连上宿主：ID 不匹配、宿主没注册、浏览器没重启 | 核对注册表 `HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.scholar.search`；重跑 `install.ps1`；重启浏览器 |
| `install.ps1` 报 `csc.exe not found` | 缺 .NET Framework 编译器 | 让用户装 .NET Framework 4.x，或从别的机器拷 `scholar-host.exe` |
| `status` 正常但检索报 `content_not_ready` | 浏览器停在错误页。**国内最常见的是代理换证**：代理软件对 `kns.cnki.net` 做 TLS 中间人，Edge 显示「隐私错误 / `NET::ERR_CERT_COMMON_NAME_INVALID`」，错误页上没有内容脚本 | 先看浏览器窗口标题。是错误页就让 `cnki.net` 直连（Clash 里加 `DOMAIN-SUFFIX,cnki.net → DIRECT`，或把 `*.cnki.net;cnki.net` 加进 `ProxyOverride`），重启浏览器；**不要**用 `curl`/`Invoke-WebRequest` 能通就判断站点没问题——它们不走系统代理 |
| 动作报 `bridge.timeout` | 窗口不在前台导致定时器节流，或标签页状态坏 | 切前台、只留一个窗口一个标签页；仍不行关掉 CNKI 标签页重来 |
| `blocked` + `cooldown_until` | 触发了风控 | **停止**。让用户人工在浏览器完成验证，再 `wensu reset --confirm`。禁止重试 |
| **全新浏览器环境第一次检索就 `blocked`（`verify_redirect`）** | 新 profile 没有 Cookie 与历史，知网要求人工验证；属预期行为 | 让用户在该窗口完成滑块验证 → `wensu reset --confirm` → 再跑一次。**不要**直接 reset 后立刻重试，reset 前必须确认验证已通过 |
| 配额用尽 | 当日 300 次用完 | 等次日自动重置，不要改 `quota.json` |

## 不要做

- 不要替用户勾选"开发者模式"或点击加载扩展，也不要伪造扩展 ID；
- 不要为了"验证能用"连续跑多次检索；
- 不要把题录写进 Zotero / EndNote / Mendeley——本项目明确不做（ADR 0006）；
- 不要在未告知用户的情况下修改系统代理设置；
- 不要删除 `state/` 下的配额与冷却文件来"绕过限制"。

## 卸载

```powershell
pwsh "$root\browser\native-host\install.ps1" -Uninstall
```

然后让用户在 `edge://extensions` 移除扩展，最后删 `$root` 与（可选的）
`%LOCALAPPDATA%\scholar-search`。
