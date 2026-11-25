# ADR 0026：用调试协议被动读取已下载的插图

- 状态：**已采纳**（2026-11-25）
- 相关：ADR 0004（风控）、ADR 0018（页面快照与 MHTML）、ADR 0023（节奏）

## 背景

`page_read` 的抓取是 `chrome.pageCapture.saveAsMHTML`。实测两份真实产物（2026-11-25）：

| 样本 | `<img>` 标签 | 进包的图片 part |
|---|---|---|
| MDPI 论文页（624 KB） | 36 | **0**（13 个 `cid:` 全是 CSS） |
| Nature 页面（690 KB） | 12 | 2（同源 SVG） |

跨域 CDN（`mdpi-res.com` 等）的 JPG/PNG **没有进 MHTML**，`<img src>` 保持绝对 URL。于是
`page.md` 离线读没有图，而 Python 端**零 HTTP**（只读边界，动作词汇封闭），无法自己补。

浏览器里那些字节确实存在（DevTools 的 Network → Img 里能看到）。问题是有没有"不新增请求"的
读取通道。逐一核过：

- `fetch(img.src)`：是**新请求**；缓存命中与否代码无法区分，且跨域读响应体受 CORS 限制。
- 页面内 canvas → `toDataURL()`：跨域图**污染画布**，无 CORS 头即 `SecurityError`。
- `webRequest` / `declarativeNetRequest`：只给请求元数据，**拿不到响应体**。
- 解析磁盘缓存：私有格式、随版本变、随时被驱逐，且属读取 profile 私有数据。
- 本地 MITM 代理：能拿，但要装 CA、接管全部流量，信任模型整体改变。

唯一"读已下载字节、不向站点再发请求"的通道是 **CDP**（`chrome.debugger`），也就是 DevTools
Network 面板本身用的那套。

## 决定

`page_read(figures=true)` 时：

1. **在导航之前**附着调试器（`goto` 携带 `assets: true`）并 `Network.enable`。
   `Network.getResponseBody` 只认识**附着期间**发生的请求，导航后再附着等于空手。
2. 只收 `type`/`mimeType` 为图片的响应；上限 **12 张 / 单张 1.2 MB / 合计 8 MB**，超出写入
   `figures.skipped` 并说明原因（`too_many` / `too_large` / `total_cap` / `no_body`）。
3. 抓完把图片放进 `<page_dir>/assets/NN.ext` 与 `assets/index.json`（URL → 相对路径），
   `page2md` 据此把 `![…](出版社CDN)` 改成本地相对链接，并把资产拷进产物目录使离线自足。
4. **抓完必然 `detach`**（`finally`），浏览器"正在被调试"提示条不跨过本次抓取。
5. 默认关闭：不开 `figures` 时一次都不碰调试器。

## 硬约束（写进实现）

- 只用 `Network.*` 的被动读取与 `Target` 的附着/离体；
- **禁止** `Runtime.evaluate`、**禁止**断点、**禁止**修改页面——注入脚本既能被站点的反调试
  探针发现，也越过本项目的"只读"立场；
- 不因抓图增加任何面向站点的请求；抓不到就如实记录，不重试、不换路。

## 后果

- `manifest.json` 增加 `debugger` 权限：权限面至今最大的一次扩张。升级后 Edge 可能要求用户
  重新确认扩展；每次带 `figures` 的抓取都会显示"正在被调试"提示条（**对用户可见，对站点不可见**：
  服务器日志里没有任何新请求）。
- 用户开着 DevTools 调试该标签页时 `attach` 会失败，返回 `figures.unavailable`，抓取照常继续，
  只是没有图。
- 附图体积计入磁盘：上限 8 MB/页，按页目录随 `pages/` 一起清理。

## 被否决的替代

见上文背景里的逐条复核。补充一条：把 MHTML 抓取改成"先把图片搬进同源页面再抓"会改动页面，
属于注入，直接违背本 ADR 的约束。
