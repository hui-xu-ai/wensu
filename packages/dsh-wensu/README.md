# 在 DSH 中安装 wensu（文溯）MCP

这是一个**配置型 bundle**：它不包含插件代码，只声明对 `@deepseek-ai/dsh-mcp-client`
的依赖，并通过 `cordis.patch.yml` 插入一条 MCP 客户端实例。

装好之后 agent 会拿到五个工具：`search` / `detail` / `detail_many` / `export` / `status`，覆盖**知网**与
**Web of Science** 两个渠道，WoS 记录自带期刊影响因子。不下载全文，只出题录。

## 版本对照

两个发行物流共用同一个版本号（ADR 0013）：看到数字不同，就说明装错了批次。

| 装什么 | 版本在哪看 | 当前 |
|---|---|---|
| DSH bundle（本目录） | npm / 插件市场 | **见当前版本** |
| `wensu` 命令本体（Python 包） | PyPI | **同上**（`pip install -U wensu`）|

两个发行物同号（ADR 0013），`scripts/check-versions.py` 会校验。这里不写死数字——上一版
写死在 README 里，发布几次之后就与包版本脱节了。

两个发行物同号，看到不一致就是装错了批次。bundle 只负责把 MCP 客户端接进 DSH，不含服务端
代码，所以它内容很少变——版本号跟着 Python 包走，只是为了让人一眼能对上。
本 bundle 走 npm 发布，**不产生 GitHub Release**；Release 只跟 Python 包的发版。

bundle 提供的工具有哪些，取决于装的那份 `wensu` 认不认渠道：

- **知网（CNKI）** —— 中文题录，中文检索式
- **Web of Science** —— 英文题录，`TS=`/`ALL=` 检索式，记录自带期刊影响因子

两者都由同一个 `search` 工具以 `channel` 参数区分，不需要装两个 bundle。

## 前置

DSH **版本必须与本 bundle 的依赖对齐**，且是**精确对应**而非"某版本以上"。

`@deepseek-ai/dsh-mcp-client` 对 DSH 的核心包声明的 peer 是**精确版本**（`dsh-llm`、`dsh-tools`、
`dsh-scope`、`dsh-timeout`、`dsh-subprocess`、`dsh-attachment`、`dsh-credentials`、
`dsh-mcp-resources`、`dsh-system-prompt` 各要求同一个完整版本号）。DSH 在导入插件行前会把这组
peer 与运行时比较，**任何一条不满足，整行就被拒**——表现是 MCP 静默不上线、工具不出现，
而 `wensu` 命令本身完全正常。

因为 `engines.dsh` 也写成了同一个精确版本，DSH 会在版本不符时**明确拒绝**这个 bundle，
而不是让它装上去再静默失效。

**实测**（2026-11-11，DSH 0.2.2-rc.2）：bundle 0.12.45 钉的是 `dsh-mcp-client@0.2.2-rc.1`，
升级 DSH 后 `mcp-scholar-search` 行状态为 `inactive`、宿主工具列表里没有任何 wensu 工具；
而直接对 `wensu serve --transport stdio` 做 MCP 握手是一切正常的。0.12.55 起改为 rc.2。

**DSH 每次升版，本 bundle 都要跟一个同版本的发行**——这不是疏忽，是精确 peer 的必然结果。

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
