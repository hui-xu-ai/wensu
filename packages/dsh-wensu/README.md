# 在 DSH 中安装 wensu（文溯）MCP

这是一个**配置型 bundle**：它不包含插件代码，只声明对 `@deepseek-ai/dsh-mcp-client`
的依赖，并通过 `cordis.patch.yml` 插入一条 MCP 客户端实例。

## 版本对照

两个独立版本流，互相不需要同步升级：

| 装什么 | 版本在哪看 | 当前 |
|---|---|---|
| DSH bundle（本目录） | npm / 插件市场 | **0.4.4** |
| `wensu` 命令本体（Python 包） | PyPI | **0.12.9**（`pip install -U wensu`）|

市场显示 0.4.4 而 `pip show wensu` 是 0.12.9 属于正常现象；bundle 只负责把 MCP 客户端接进 DSH，
不含服务端代码。本 bundle 走 npm 发布，**不产生 GitHub Release**；Release 只跟 Python 包的发版。

bundle 提供的工具有哪些，取决于装的那份 `wensu` 认不认渠道：

- **知网（CNKI）** —— 中文题录，中文检索式
- **Web of Science** —— 英文题录，`TS=`/`ALL=` 检索式，记录自带期刊影响因子

两者都由同一个 `search` 工具以 `channel` 参数区分，不需要装两个 bundle。

## 前置

DSH **0.2.2-rc.1 及以上**（`0.3.0` 前）。DSH 在导入插件行前会把 `@deepseek-ai/dsh-mcp-client`
声明的 DSH peer 版本与运行时比较，未满足则整行被拒（MCP 静默不上线、工具不出现），所以
bundle 的依赖版本必须与 DSH 版本对齐。

`wensu` 命令必须在 DSH 进程的 PATH 上，浏览器侧也要装一次：

```powershell
pip install wensu
wensu setup        # 复制浏览器资源并注册原生宿主
wensu status       # bridge_ready: true 才表示整条链路通了
```

`wensu setup` 会打印扩展目录；在 `edge://extensions`（或 `chrome://extensions`）打开开发者模式，
用“加载解压缩的扩展”选中该目录即可。没有浏览器侧时 MCP 服务仍会启动，但 `search` 会返回桥接错误。

## 安装

在 DSH 的插件管理入口（桌面端 Plugins 页面，或在 Creator 会话里让 agent 调用
`plugin_manager`）安装这个目录。安装时 DSH 会解析并安装
`@deepseek-ai/dsh-mcp-client@0.2.2-rc.1`，不需要手工复制 `node_modules`，也不要手工编辑
profile 的 `cordis.patch.yml`。

安装完成后**完全重启 DSH**，新会话中应出现：

- `mcp__wensu__search`
- `mcp__wensu__detail`
- `mcp__wensu__export`
- `mcp__wensu__status`

## 验证

重启后调用 `mcp__wensu__status`。返回 `bridge_ready: true` 即表示 MCP 客户端已启动并能
连到浏览器宿主。

## 卸载/回滚

在插件管理入口卸载 `@hui-xu-ai/dsh-wensu`，重启 DSH 即可。不要直接删除 profile 里的文件。

## 备选：任何 MCP 客户端

JSON 配置（Claude Desktop、Cursor 等）：

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

Codex 用 `~/.codex/config.toml`，不是 JSON：

```toml
[mcp_servers.wensu]
command = "wensu"
args = ["serve", "--transport", "stdio"]
```
