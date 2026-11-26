---
name: scholar-batch-read
description: 批量读取多篇文献全文（wensu）——按出版社分组、串行抓取、遇验证墙叫人点或跳过该出版社、每条成功即交子代理离线转换、失败统一记账并在收尾汇报。用于"一次读一批 DOI"的场景。
---

# 批量读取文献全文

一次读一篇用 `page_read` 就够；**这篇 skill 只处理"一批"**。核心是两件事：**同出版社的文献放在一起抓**（一次人工验证覆盖一整组），**每条成功立刻外移**（离线转换不占浏览器）。

## 开工前：把账算清楚

| 项 | 规则 |
|---|---|
| 预算 | 每篇约 2 额度（私有镜像形态可能 2/篇；公开版 1–2），预热每家 1 额度。先 `status` 读 `quota_remaining`，不够就停 |
| 分组 | 按 `publisher` 分组；组内不得穿插别家（一条 `page_read` 只服务一篇） |
| 并发 | **浏览器侧永远 1 条**；并行只发生在离线转换（子代理） |
| 禁止 | 不并发抓取、不自动重试同一页、不破解验证、不换 IP、不加延时重试；遇 `403/429` 整批停 24 h |

## 步骤

### 1. 分组

`search`/`detail` 拿到的每条都带 `publisher`。按它分组，组内按 DOI 排序；把"上次失败的"排在最前（重试时）。

### 2. 预热（可选，但强烈建议）

每一组开工前，为该组出版社各挑**一篇**文献做预热：

```
warm_up(targets: ["10.1007/s10853-...", "10.1016/j.cej....", "10.1002/adma...."])
```

- 默认四家：SpringerLink、ScienceDirect（Elsevier）、Wiley、ACS；IEEE 目前不需要；其余按用户选择。
- **先告诉用户成本**（每家 1 额度 + 1 次访问），再调用。
- 调用后对用户说一句："这几个标签页如果出现了验证，请依次点一下；点完告诉我，我开始抓。"

### 3. 串行抓取

对组内每条依次 `page_read(doi=...)`，**一次一条，拿到结果再发下一条**。

拿到回包先读三个字段：

| 字段 | 怎么用 |
|---|---|
| `terminal` | `ok` 继续下一条；`partial` 记为"读到了但不是全文"；`blocked` 立刻停手；`timeout` **跳过本组剩余**；`no_page`/`unsupported_site` 记失败继续 |
| `stage` | 判断卡在哪：`wall`＝验证，`identity`＝抓错页，`capture`＝抓到但非全文，`navigate`＝没打开 |
| `full_text_reason` | `paywall`/`pdf_only`/`abstract_only`/`no_body` —— 这是**页面事实**，不要替用户推断"没有订阅" |

**`terminal == "ok"` 时立刻外移**：把 `mhtml_path` 与 `capture_sha256` 交给一个子代理（`subagent`），让它调 `page2md(mhtml_path=...)` 并做阅读/摘录。主流程**不要等它**，继续下一条。子代理回报里必须带 `capture_sha256`，便于回查"这份 Markdown 出自哪次捕获"。

### 4. 遇验证墙

- `terminal == "blocked"`（可见验证码 / 403 / 429）：按硬约束**立即停**。403/429 冷却 24 h，整批结束。
- `terminal == "timeout"`（`reason: verification_timeout`，工具已把窗口最大化并等了 10 s）：**记失败，跳过该出版社剩余条目**，换下一组。不要重试同一页。

### 5. 失败账本

每条失败写进 `work/reports/<run-id>/failures.json`：

```json
{"doi": "…", "publisher": "wiley", "terminal": "timeout",
 "reason": "verification_timeout", "stage": "wall",
 "evidence": {"title": "请稍候…", "captured_url": "…"},
 "quota_charged": 1, "job_id": "…"}
```

### 6. 收尾汇报（全部跑完之后，一次说清）

```
成功 N 篇（已交子代理转换：…）
失败 M 篇：
  - 验证未清（wiley 2 篇）：可能需要在浏览器里点一次验证后重试
  - 只有 PDF（acs 1 篇）：页面没有 HTML 全文
  - 未收录（1 篇）：出版社不在白名单
要重试失败的这些吗？（重试前我会重新预热对应出版社）
```

**不要**边跑边逐条汇报；只在"整批结束"或"必须停"时说。

## 反模式（看到就停手）

- 同时发多个 `page_read`（浏览器侧仍会排队，但账目会乱）
- 为同一篇连续调 `page_read(refresh=true)`
- 把 `terminal: timeout` 当"失败但可立即重试"
- 把 `full_text_reason: paywall` 直接说成"你没有订阅"——只说"这页只给了付费墙"
- 抓到 `partial` 还把它当全文交给子代理做结论
