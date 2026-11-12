# 0017 · DSH bundle 对插件依赖与 DSH 版本都做精确锁定

**状态**：已接受（2026-11-11）
**取代**：ADR 0013 中"bundle 的 `engines.dsh` 用范围表达兼容"的做法
**触发**：DSH 升级到 `0.2.2-rc.2` 后，wensu 的 MCP 工具从宿主工具列表里消失

## 背景

`@hui-xu-ai/dsh-wensu` 是一个**配置型 bundle**：它不含插件代码，只声明对
`@deepseek-ai/dsh-mcp-client` 的依赖，并插入一行 `mcp-client`。

原来的声明是：

```json
"dependencies": { "@deepseek-ai/dsh-mcp-client": "0.2.2-rc.1" }   // 精确
"engines":      { "dsh": ">=0.2.2-rc.1 <0.3.0" }                  // 范围
```

`dsh-mcp-client@0.2.2-rc.1` 对核心包声明的 peer 是**精确版本**（`dsh-llm`、`dsh-tools`、
`dsh-scope` 等十个）。DSH 升到 rc.2 后这十条 peer 全部不满足，**整行被拒**：

```
配置项 include:mcp-scholar-search → status: inactive
宿主工具列表 → 没有任何 mcp__wensu__* 工具
wensu 命令本身 → 完全正常（bridge_ready: true，stdio 握手成功）
```

而 `engines` 给的是范围，rc.2 **满足**它，所以版本闸门无事可做，**静默失效**。

## 决定

`dependencies` 与 `engines.dsh` 都写成**同一个精确版本**（当前 `0.2.2-rc.2`），并在
`packages/dsh-wensu/README.md` 写明：**DSH 每升一个版本，本 bundle 必须跟一个同版本发行**。

## 理由

- `engines` 的职责是**声明真实兼容性**。写范围而依赖只认单一版本，等于让闸门说谎——
  这正是本次故障能静默发生的原因。
- 精确 `engines` 把"静默失效"换成"安装/激活时明确拒绝"，用户能看见发生了什么。
- 代价（每次 DSH 升版都要发一个 bundle）是精确 peer 的**必然结果**，不是可以绕开的麻烦：
  换范围只会把不匹配从安装期推迟到运行期。

## 被否的替代方案

| 方案 | 否决原因 |
|---|---|
| 保留宽松 `engines`，靠文档提醒 | 已经证明没人会在升级 DSH 时去读 bundle 的 README |
| 把 `dsh-mcp-client` 声明为 `peerDependency` 交给宿主提供 | 该插件并非 DSH 内置（内核 bundle 里没有它），宿主不会提供 |
| 依赖写成 `^0.2.2-rc.2` 范围 | 安装时会解析到最新 rc，而 peer 仍是精确版本，不匹配依旧存在且更隐蔽 |
| bundle 内联一份 mcp-client 实现 | 复制核心插件，与本项目"不改内核"的取向冲突 |

## 后果

- 发布流程需增加一步核对：**bundle 的 `engines.dsh` 是否等于当前 DSH 版本**。
- 用户侧遇到"工具消失"时，第一个要查的是 `include:mcp-scholar-search` 的 `status`
  与 profile 里 `dsh-mcp-client` 的版本，而不是 `wensu` 本身。
