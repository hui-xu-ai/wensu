# ADR 0008 · WoS 渠道所需的三处内核改动

- 状态：accepted
- 日期：2026-11-08
- 关联：ADR 0007（WoS 取数方式）、ADR 0002（只读）、`docs/channel-contract.md`

## 背景

WoS 渠道（ADR 0007）决定**拦截页面自己的结果流**，拿到的是 NDJSON 文本而不是 HTML。
现有内核有两处假设与这个形态不符，另有一处风控判定只认 CNKI 的信号：

1. `core/service.py` 的 `_html()` 只从动作结果里取 `data["html"]`，而 `read_text` 返回的是
   `data["text"]`，解析器拿不到载荷；
2. `extension/content/actions.js` 的 `read_text` 用 `innerText`（渲染后文本，空白被折叠），
   而 NDJSON 的空格与换行必须原样保留；
3. `core/risk.py` 的 URL / 标题 marker 全部来自 CNKI（`/verify/home`、`fsso.cnki.net`、中文标题），
   WoS 撞上 SSO 跳转或 "Session Expired" 时不会触发 24 小时冷却。

约束：不改九动词集合（AGENTS 第 6 条）、不申请新扩展权限、不动 `record.json`。

## 备选

### 备选 A：完全不改内核，用 `read_html` + 正则提取

- 优点：零内核改动。
- 被否理由：`read_html` 在 `actions.js` 里被 `MAX_HTML_BYTES = 1_000_000` 截断，而一次捕获是
  500 KB 左右、页面自身 HTML 也在同一量级，两者相加必然超限——截断后的 NDJSON 解析不出后
  半部分记录，属于**静默数据错误**，比报错更糟。

### 备选 B：新增第 10 个动词 `read_stream`

- 优点：语义最清晰，`read_text` 保持原样。
- 被否理由：撞 AGENTS.md 第 6 条「动作词汇封闭」，需要同步改 native host、扩展、`policy.py`、
  `params.py` 与全部渠道契约测试；为一个按需特性支付全局词汇变更，代价与收益不对等。

### 备选 C：三处最小改动（选中）

- 优点：改动集中在 3 个文件、约 20 行，全部向后兼容；CNKI 的 plan 从不使用 `read_text`
  （已 grep 确认只用 `read_html`），因此默认行为不变。
- 被否理由：`_html()` 的名字变得不够精确（它现在也可能返回文本）。

## 决策

采用备选 C，具体如下：

1. **`core/service.py` · `_html()`** 依次尝试 `data["html"]`、`data["text"]`，并把错误文案改为
   `plan produced no page payload`。函数名保留，docstring 说明「页面载荷」既可以是文档也可以是捕获的文本。
2. **`core/params.py` + `extension/content/actions.js` · `read_text`** 增加可选参数
   `mode`（默认 `"inner"`，保持现有语义）；`mode: "text"` 时读 `textContent`，不做空白折叠。
3. **`core/risk.py`** 的 `VERIFY_URL_MARKERS` 增加 `recaptcha` / `hcaptcha`；
   `LOGIN_URL_MARKERS` 增加 `sso` / `shibboleth` / `carsi` / `session-expired`；
   标题判定抽成 `RISK_TITLE_MARKERS` 并对标题做 `casefold`，补 `session expired` /
   `sign in` / `access denied`。

**版本**：`0.4.2 → 0.5.0`。新渠道的 manifest 声明 `min_core: "0.5.0"`，因为它在旧内核上拿不到载荷。

**明确不做**：配额与冷却**仍为全局单例**。两者共享更保守——任一渠道撞上风控，说明当前网络
环境或账号已被盯上，让另一个渠道继续发请求才是真正的风险。按渠道隔离留待后续 ADR，届时
需要同时修改 `RiskGuard`、`Planner`、`ScholarService` 与 `bootstrap`。

## 后果

- CNKI 的行为不受影响：它的 plan 只用 `read_html`，`read_text` 的默认 `mode` 未变，
  marker 扩展只增加匹配项。
- 新增契约测试覆盖最坏计划（`page=3` + `sort=date`）：**23 个动作、109 s、7 个网络动作**，
  都在内核上限（40 动作 / 120 s）之内；默认路径仍是 **3 个网络动作**。
- 若未来某渠道需要真正的流式读取（超过 2 MB 的 `MAX_FRAME_BYTES`），仍应走备选 B 的路径。
