# 方案：用 CDP 被动读取已下载的图片（`page_read(figures=true)`）

状态：**待用户确认三处取舍**（参数形态 / 权限代价 / 体积上限）。确认后按本文实施。

## 背景（实测）

- `page_read` 的抓取是 `chrome.pageCapture.saveAsMHTML`：序列化 DOM + 它愿意带的资源。
  实测两份真实产物：MDPI 一页 36 个 `<img>`、**0 个图片 part**（13 个 `cid:` 全是 CSS）；
  Nature 一页 12 个 `<img>`、只带进 **2 个同源 SVG**。跨域 CDN（`mdpi-res.com` 等）的图**没进包**。
- 因此 `page.md` 里图片是出版社外链，离线裂图；Python 端**零 HTTP**，不能自己补抓。
- 浏览器的响应体**没有任何扩展 API 可直接读**：`fetch` 是新请求（缓存命中与否不可分辨）、
  Canvas 会被跨域污染、`webRequest` 拿不到响应体、磁盘缓存格式私有。
  唯一“不新增请求”的通道是 CDP，即 `chrome.debugger`。

## 决定

`chrome.debugger` 附着工作标签页，**只读** `Network.*` 的已下载响应体；默认关闭，按调用开启。
禁止 `Runtime.evaluate`、禁止断点、禁止改页面（写进 ADR）。

## 实现（复用现有 token/offset 分片通道，不动动作词汇）

现有分片机制：`snapshot(tab)` 把 MHTML 存进 SW 的 `captures` Map 并回一个 `token`，
内核再用 `snapshot(token, offset)` 逐片取 —— 单帧上限 `MAX_FRAME_BYTES = 2 MB`，图片同样走这条。

1. **`goto` 增加参数 `assets: true`**（已有动词的新参数，允许）：
   扩展在 `chrome.tabs.update` **之前** `chrome.debugger.attach({tabId}, "1.3")` + `Network.enable`，
   监听 `Network.responseReceived`（`type === "Image"`），按 `requestId` 记 `{url, mime, size}`；
   `Network.loadingFinished` 标记完成。
   *为什么必须在导航前附着*：`getResponseBody` 只能读到**附着之后**发生的请求；导航后再附着等于空手。
2. **`snapshot` 增加参数 `assets: true`**：抓完 MHTML 后对记录的图片逐个
   `Network.getResponseBody({requestId})`（base64），存进同一个 capture 条目
   `assets: [{url, mime, b64}]`，回包**只给清单**（`[{url, mime, size}]`），不发字节。
   随后 `chrome.debugger.detach()`。
3. **分片取图**：`snapshot(token, asset: n, offset)` 返回该图片的第 n 片；内核循环取完落盘
   `<out>/assets/<序号>-<可读名>.<ext>`。
4. **内核**：`page_read(..., figures=false)`——为 true 时给 goto/snapshot 带上 `assets: true`，
   按清单逐片取图落盘，并把 `url → assets/<file>` 映射交给 `page2md` 重写 Markdown 图片链接。
   `meta.json` 记录 `figures: {saved: n, skipped: [{url, reason}], bytes: N}`。
5. **上限**（超限只留外链 + warning）：最多 **12 张**、单张 **≤ 1.2 MB**、合计 **≤ 8 MB**；
   非 http(s)/data 的跳过；失败记录原因（超限 / 取字节失败 / 未在页面 `<img>` 里出现）。
6. **权限**：`manifest.json` 加 `"debugger"`。副作用要说清：升级后 Edge 可能要求用户重新确认扩展；
   抓取期间浏览器显示“正在调试此浏览器”提示条（结束即 detach，提示条消失）。
7. **测试**：`tests/js/` 加假 `chrome.debugger`（记录 attach/enable/事件/离体），断言
   ①导航前附着 ②只收图片 mime ③超限跳过并记录 ④结束必然 detach；Python 侧加
   分片取图 + URL→文件重写 + 上限裁剪的用例；`schemas/tools.json` 重新生成（`tool-schema` 门会验）。
8. **文档**：ADR 0026（含备选与拒绝理由）、CHANGELOG、`skills/scholar-search` 补一句
   「要图用 `figures: true`，仅在需要时开」。

## 不做

- 不用 `fetch` 逐图下载（可能变成新请求，代码无法区分命中缓存还是回源）。
- 不用 MITM 代理、不解析磁盘缓存。
- 不注入脚本、不设断点、不改页面（CDP 仅 `Network.*` + `Target` 附着/离体）。
