# 0.14.54 离线复核 · 真实捕获（F53-01/02/03）

日期：2026-11-27。输入是 0.14.53 真实验收保存的捕获，**本轮不访问任何网站**。

- 捕获：`…/real-0.14.53-1a70620c/pages/10.3390_s26041303/page.mhtml`（675,957 B）
- 脚本：`work/verify/2026-11-27-real-capture-0.14.54/check.py`（可重跑，退出码 0 = 通过）

## 结果

| 观测 | 0.14.53 | 0.14.54 |
|---|---|---|
| `tables_rendered` | 0 | **3** |
| `table_rows` | 0 | **25** |
| 布局表（单行，未计入正文） | — | 1 |
| 渲染失败（未归位） | — | 0 |
| `Sample Composition` | 缺失 | ✓ |
| `Manufacturing Technique` | 缺失 | ✓ |
| `Tensile Strength` | 缺失 | ✓ |
| `Mean Absolute Angle Error` | 缺失 | ✓ |
| `pdf_url` | `…/journals/3/flyer.pdf`（宣传册） | `https://www.mdpi.com/1424-8220/26/4/1303/pdf` |
| `citation_doi`（`declared_doi` 的来源） | `10.3390/s26041303` | 同 |
| 分节文件数 / index 条目数 | 16 / — | 17 / 17，**每条都有对应文件** |
| index 分节 token 求和 vs `total_tokens` | — | 7825 / 7825 |

`tokens_total` 从 7421 涨到 7825，差额来自新纳入的三张表（`Tables` 一节 404 token，其余分摊到
Results 各节）；索引自身的求和与 `total_tokens` 一致，分节文件与索引条目一一对应。

## 一个我在脚本里改掉的错误比较

第一版脚本用 `page2md._word_count` 去"核对"索引的 `tokens`，得到 4349 vs 7825，看着像不一致。
**那不是产品缺陷，是我拿两个不同的度量对比**：`tokens` 是索引用的估算器，`_word_count` 是散文词数。
脚本现在比较"索引自身求和 vs `total_tokens`"，并检查每个索引入口都有对应分节文件。

## 边界

- 这是**离线复核**，只证明 `page2md`/`pageprobe` 在真实捕获上的行为；不证明线上页面结构不变。
- 公式仍是 19 个只有 MathJax 图形、无 LaTeX 的告警，本轮**没有**改善，也没有宣称改善。
- 覆盖率的 0.597 用的是把页面噪声算进分母的粗暴口径；这个数不能读成"丢了 40% 正文"。
