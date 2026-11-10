---
name: scholar-detail
description: 通过 scholar-search MCP 服务读取单篇文献详情（摘要、DOI、卷期页、关键词、单位）。只读，不下载全文。
---

# 文献详情

## 何时使用

- 已有 `search` 返回的 `url`（知网或 WoS 都接受），或者一个裸 DOI；
- 需要摘要、DOI、卷期页、作者单位、关键词；
- 需要判断这篇是网络首发还是正式刊出。

## 两个渠道都支持

| 渠道 | 怎么给 | 费用 |
|---|---|---|
| 知网 | `url` 或 `j.cnki.` / `d.cnki.` 前缀的 DOI | **列表不播种详情**，第一次取扣 1；再取同一篇扣 0 |
| WoS | `url` 或其它 DOI | **列表已播种完整题录**（除摘要），`detail` 命中缓存扣 0 |

**渠道由 URL 的域名或 DOI 前缀推断，不用手动指定。** 只有推断不出来时才传 `channel`。

## 硬约束

1. 接受知网、WoS 两个渠道的 `https` 链接，以及裸 DOI；内核会校验域名。
2. 返回 `blocked` 立即停止，禁止重试。
3. 一次调用只取一篇；每篇之间必须由用户明确发起，不要为了凑数量连续循环调用。
   要批量取，用 `detail_many`。
4. 不下载、不请求 PDF/CAJ。
5. `include_abstract` 默认 `false`。摘要约 1200 字（中文）/ 1000 字符（WoS），
   只对确定要交付的记录打开。

## 调用

工具：`detail`

```json
{"url": "https://kns.cnki.net/kcms2/article/abstract?v=..."}
{"url": "10.13841/j.cnki.jxsj.2026.11.001"}
{"url": "https://webofscience.clarivate.cn/wos/woscc/full-record/WOS:001218812900001"}
```

## 返回字段

| 字段 | 说明 |
|---|---|
| `title` | 已去掉“附视频”等后缀 |
| `authors` | 姓名列表，不含单位角标 |
| `institution` | 作者单位，可能含多个 |
| `source` | 刊名 |
| `year` | 年份 |
| `volume` / `issue` / `pages` | 卷、期、页码；**网络首发文章为空** |
| `doi` | DOI；部分网络首发也为空 |
| `abstract` | 摘要正文 |
| `keywords` | 关键词列表 |
| `citations` / `downloads` | 被引、下载（列表页才有，详情页通常为空） |

## 判读

- `volume`/`issue`/`pages` 全空 + `year` 有值 → 大概率是网络首发，不是解析失败；回答时要说明。
- 详情页出现“安全验证”标题时服务会返回 `blocked`，这是真实验证页，不是网络问题。

## 不要做的

- 不要用详情接口批量刷页面；
- 不要把空卷期当成“工具坏了”；
- 不要拼凑未返回的字段（例如自行推测 DOI）。

