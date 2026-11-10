---
name: scholar-export
description: 把 scholar-search 返回的题录导出为 RIS/EndNote/Markdown/CSV 文本，用于 Zotero、EndNote、NoteExpress 导入或制表；不涉及全文下载。
---

# 题录导出

## 何时使用

- 用户要把检索结果导入文献管理器；
- 需要 `.ris` 或 EndNote 文本；
- 需要核对导出条目与来源是否一致。

## 硬约束

1. 导出的是**题录文本**，不是全文，也不产生任何下载请求。
2. 只导出工具实际返回的字段；缺失字段留空，不编造。
3. 导出前确认 `records` 来自 `search` 或 `detail` 的返回，不要手工拼。

## 调用

工具：`export`

```json
{"records": [{"title": "…", "authors": ["…"], "source": "…", "year": 2026, "url": "…"}], "format": "ris"}
```

`format` 取值：`ris`、`endnote`、`markdown`、`csv`。前两种是引文格式（给 Zotero/EndNote 导入）；后两种是展示导出，带影响因子和它的 JCR 年份，但不是完整元数据备份。

## 返回

```json
{"format": "ris", "text": "TY  - JOUR\nTI  - …\n…"}
```

把 `text` 原样保存为 `.ris` 或 `.enw` 文件即可导入。

## 质量检查

- `TY  - JOUR` 表示期刊论文；
- 至少应有 `TI`、`AU`、`T2`（刊名）、`PY`、`UR`；
- 中文文献不需要翻译字段。

## 不要做的

- 不要在导出时偷偷补 DOI 或卷期；
- 不要声称“已下载全文”；
- 不要把 RIS 文本再喂回检索接口。

