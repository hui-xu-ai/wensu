# 版本与兼容性

**一个版本号，四个发行物。** 从 0.12.10 起，Python 包、浏览器扩展、native host 与 DSH bundle
共用同一个版本号，发版时一起走。看到任何地方写着 `0.12.10`，它们都是同一批东西。

## 版本号写在哪

发版前这五处必须一致（`scripts/check-versions.py` 会校验）：

| 位置 | 用途 |
|---|---|
| `pyproject.toml` → `version` | PyPI 包版本 |
| `src/scholar_search/__init__.py` → `__version__` | 运行期 `wensu --version` |
| `extension/manifest.json` → `version` | 浏览器扩展版本 |
| `packages/dsh-wensu/package.json` → `version` | npm bundle 版本 |
| `NOTICE` → `Version:` | 发布声明 |

## 为什么统一

此前是三套版本号（Python 0.12.x / 扩展 0.5.x / bundle 0.4.x），每一个都能自圆其说：
扩展改得少、bundle 只动一行配置。但合起来只产生一个问题——**使用者无法判断手里这几个
东西是不是一套**。装完 bundle 看见 0.4.5、`pip show wensu` 看见 0.12.10、扩展详情页写着
0.5.0，而这个组合到底能不能用，没有任何地方能查到。

统一之后，版本号本身就是兼容性声明：**相同即配套，不同即不配套**。

npm 上 0.12.10 之前的 0.4.x 是历史版本，保留可装，但不再演进。

## 兼容性仍由三份契约定义

版本号统一解决的是「是不是一套」，契约解决的是「怎么配合」。

### 契约一 · 桥协议版本

```
PROTOCOL_VERSION = 1
```

- 定义在 `adapters/bridge/host.py`，扩展侧 `background.js` 各一份相同的常量。
- **强制校验**：内核发 `hello` 带 `protocol`，宿主回复必须等于同一值，否则握手失败。
- **不匹配的表现明确**：`bridge_ready: false`，每个动作都失败，不会半工作。
- **升级规则**：改握手语义时两侧同时改、同时递增。

### 契约二 · 能力与渠道

- 有哪些渠道：`wensu status` 的 `channels`。
- 某渠道的可选能力：`manifest.capabilities`（`journal` / `export` / `journal_metrics`）。
- **不匹配的表现明确**：请求不存在的能力会抛错，例如
  `channel 'cnki' does not report journal metrics`。不做静默降级。

### 契约三 · bundle 与 wensu

bundle 不含检索代码，它只让 DSH 启动 `wensu serve --stdio`。统一版本号之后，
bundle 与 `wensu` 同号，装的时候看到数字不一致就是装错了。

## 自查

```powershell
wensu --version      # 应等于扩展详情页与 market 上显示的版本
wensu status
```

```json
{
  "version": "0.12.10",
  "bridge_protocol": 1,
  "channels": ["cnki", "webofscience"],
  "bridge_ready": true
}
```

| 症状 | 说明 | 处理 |
|---|---|---|
| `bridge_ready: false` | 宿主没连上，或协议版本不匹配 | 先看 `status.bridge.remediation`；再看 `status.bridge.log_path` 指向的日志 |
| `channels` 少一个 | 渠道目录缺失或 manifest 被拒 | 检查 `channels/*/manifest.json` |
| `version` 与扩展详情页不一致 | 装的是不同批次 | 重装配套的那一套 |
| 工具在 DSH 里没出现 | bundle 的 MCP 客户端没连上 | 看 DSH 侧 `dsh-mcp-client` 的启动错误 |

### 版本号不一致时，哪些情况真有问题

`version` 是**发行批次**，`bridge_protocol` 是**线上协议**。判断兼容只看后者：

| 情况 | 是否兼容 | 说明 |
|---|---|---|
| `version` 相同，`bridge_protocol` 相同 | ✅ | 配套 |
| `version` 差几版，`bridge_protocol` **相同** | ✅ | **正常**。协议没变就能通；例如扩展 0.12.15 + MCP 0.12.20 |
| `bridge_protocol` **不同** | ❌ | 协议断了。扩展侧会在连接时拒绝并写日志 |

**所以：看到版本号不同先别急着重装**，先跑 `wensu status` 比 `bridge_protocol`。
两侧都强制校验这个数字，不匹配会在握手阶段直接断掉，不会静默出错。

扩展**不需要**跟 MCP 同步升级——只有当 `bridge_protocol` 变了才需要。ADR 里记着当前值，
`check-versions.py` 会校验两侧一致。

## 发版

两条流水线，互不依赖，但**共用版本号**：

- Python 包：改五处版本 → 提交 → 打 `v*` tag → 推 → CI 发 PyPI + Release
- bundle：同一提交里改好 → 打 `npm-v*` tag → 推（或本地 `pnpm publish`）→
  **发布成功后**再更新 `docs/market/index.json`

详见 `docs/publishing.md`。
