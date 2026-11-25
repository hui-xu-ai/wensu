# 0025 · 撞墙在导航途中就认出来，不再为它等满 13 秒

**状态**：已接受并实现（2026-11-25，0.14.5 待发）
**相关**：ADR 0004（风控即停）、ADR 0019（出版社页读取）、ADR 0022 修订 1（验证页不冷却）

## 背景

`page_read(doi: "10.1002/adma.75384")` 首次调用撞上 Wiley 的人工验证页，实测 `goto` 用了
**12.12 s**（2026-11-25 验收 D2）。拆开看：

1. `waitNavigated` 很快返回（URL 已跳到验证页）；
2. `waitComplete` 接着轮询 `tab.status === "complete"`，**而验证页永远不会触发 load 事件**
   —— 这一点扩展自己的注释里早就写着（`background.js:581`）；
3. 于是整整 12 s 花在一个已经定型的页面上，最后只换来一句「请人工验证」。不留文件、不产出内容，
   只扣 1 额度（这是对的，但 12 秒什么也没买到）。

同样的浪费还有第二种形态：Cloudflare 的质询页**就挂在文章本来的 URL 上**，此时连 URL 都不变，
`waitNavigated` 也会陪跑到 10 秒上限。

## 决定

**把「哪些页面值得提前放弃等待」的判断依据，由内核通过 `goto` 参数传给扩展。**

- `goto` 新增两个可选参数：`halt_url_markers`、`halt_titles`（都是字符串数组，≤32 条、每条 ≤80 字符，
  由 `core/params.py` 校验）。缺省为空 = 行为与改动前完全一致。
- 取值只有一处来源：`core/risk.py` 的 `VERIFY_URL_MARKERS` 与 `RISK_TITLE_MARKERS`
  （`ScholarService._page_goto_params` 原样传过去）。**扩展里不长第二份清单**，它不认识「验证页」，
  只认识「URL 含这些片段 / 标题以这些词开头」。
- 扩展在导航期间并行跑一个 watcher（250 ms 一次 `chrome.tabs.get`）：
  - 命中 URL 片段，或标题以某个词**开头** → 记下命中时刻；
  - **宽限 1.5 s**：期间 URL 或标题变了（质询自己过了）→ 取消，回到原来的等待；
  - 宽限期满仍命中 → 结束等待，回 `data.halted = true` 与当前 URL/标题。
- 判定权仍在内核：`RiskGuard` / `challenge_in_title` 依旧用它更严的规则（精确匹配，或前缀 + 站点名、
  无 CJK、≤32 字符）决定 `blocked`。扩展这一侧故意更**宽**——多停一次只损失一次停顿，
  而误报「不是墙」会去抓一个空页面。

预期：Wiley 那种墙从 12.1 s 降到 **约 2 s**（1 s 内标题就位 + 1.5 s 宽限）；正常页面**一点不变**
（无命中就照原样等，它是 Promise.race 里先完成的那条）。

## 被否的替代方案

- **把墙标题清单写进扩展**（扩展自己判）。否决：两份清单必然漂移，而这份清单是踩过坑才长出来的
  （「Access Denied: 论跨境数据主权」曾误判冷却一整天，`risk.py` 里有记录）。
- **只按 URL 判**。否决：Cloudflare 大量质询页挂在原 URL 上，URL 完全不动。
- **缩短 `waitComplete` 的预算**（例如 13 s → 3 s）。否决：重页面真的需要 13 s（Wiley 实测 13.3 s），
  砍预算就是把「慢」换成「错」。
- **在 Python 侧把 `goto` 拆成 `wait: "none"` + `sleep` + `read_text` 再判**。否决：正常路径的等待语义
  会跟着变（这是 `page_read` 的happy path），而且 `read_text` 依赖内容脚本——导航途中它可能根本不在。
  扩展侧提前退出对正常路径是零影响。
- **不加宽限期，命中即停**。否决：质询页自解时（Cloudflare 的 JS challenge）标题在前一两秒就是这个样，
  不设宽限会把一次本来能成功的读取变成 `blocked`。

## 兼容性（实现时踩到的）

**新参数是「包与宿主必须同版本」的改动。** 参数校验发生在两处：内核的 `validate_params`，
以及**原生宿主**的 `BridgeHost.request → validate_request → validate_params`
（`adapters/bridge/host.py:160`）。宿主是浏览器按 `native-host/python-path.txt` 指定的解释器
拉起来的独立进程，它 import 的是**安装版**包：

```
python-path.txt = D:\Python\Python314\python.exe
→ D:\Python\Python314\Lib\site-packages\scholar_search   （0.14.4 wheel，不认识 halt_*）
```

所以「仓库源码 + 已装好的宿主」这种开发组合会让 `page_read` 直接 `policy.params` 失败
（实测 2026-11-25）。正式发版不受影响——`wensu setup` 同时铺扩展与宿主，宿主跟着包一起升级；
但**真机调试时需要让宿主也跑仓库代码**：把 `python-path.txt` 指向仓库 venv
（`…\scholar-search\.venv\Scripts\python.exe`，editable 装到 `src/`）再重载扩展，
或先 `pip install` 新版到那个 python。

## 回滚

删掉 `_page_goto_params` 里的两个键即回到旧行为（扩展对缺省参数是 no-op）；不想动 Python 时，
把 `GATE_WATCH_MS` 设为 0 同效。

## 验证

- 单测：`tests/unit/test_wall_early_exit.py` —— 参数从内核单一来源传出、真实清单能过 schema、
  畸形清单被拒、无标记时行为不变。
- 扩展行为：`tests/js/gate_watch_probe.js`（真 `background.js` + 假 `chrome`，与
  `test_extension_tab_lifecycle.py` 同一套路）实测三种形态：

  | 形态 | 结果 |
  |---|---|
  | 撞墙（title「请稍候…」，**永不 complete**） | **1,549 ms** 返回，`halted: true`，标题如实带回 |
  | 质询自解（0.6 s 后变成文章标题 + complete） | **785 ms** 返回，`halted: false`，带的是文章标题 |
  | 无标记（正常加载） | **15 ms**，`halted: false`，与改动前一致 |

  对照报告 D2 的 `goto` 12,116 ms：撞墙这条从 12.1 s 降到约 1.5 s。
- **仍未验证**：真实站点的“永不完成”的撞墙。2026-11-25 下午真机撞到了同一篇 Wiley 墙，但那个
  质询页**自己完成了加载**（`goto` 989 ms 返回、`halted` 缺省、标题「请稍候…」），于是既没有可省的
  等待，也没有触发提前退出——内核照样按标题判 `blocked`、扣 1、不落盘。报告 D2 的 12.12 s 属于
  “永不 complete”那种形态，无法按需复现。
  结论：**本 ADR 的收益只在质询页挂住时体现**；没命中的后果是退回改动前的行为，不会误报。
