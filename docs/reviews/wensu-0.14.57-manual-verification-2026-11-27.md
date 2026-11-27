# wensu 0.14.57 · 人工完成验证后唤醒抓取验收

日期：2026-11-27，Asia/Shanghai。使用官方安装，不含私有导航补丁。

结论：用户手动完成 ScienceDirect 验证后，官方等待动作返回 `cleared=true`；随后对现有标签抓取成功，文章 URL、DOI 和正文均匹配，并生成 Markdown。这次唤醒没有重新导航，额外配额为 0。**这是一次新的“唤醒→等待→抓取”流程，不能视为此前已超时的公开 `page_read` 调用恢复成功。**

## 1. 基线与操作范围

- 安装：`C:/Users/xuhui/AppData/Local/scholar-search/installations/0.14.57/venv/`。
- 新 Python 进程加载官方安装；`core/page_nav.py` 与 wheel RECORD 摘要一致，`page_warmup.json` 不存在。
- 实际 worker=`background-0.14.57.js`，handshake=`ok`，host_version=`0.14.57`，coordination_writable=`true`。
- 目标：`https://www.sciencedirect.com/science/article/pii/S1385894723029534`。
- 沿用现有浏览器会话，未改 Cookie、缓存、配额、冷却、租约或浏览器配置。
- 没有自动操作验证控件，没有重新导航或刷新站点，没有下载 PDF/CAJ。

当前聊天旧 MCP 连接不可用，因此本次使用官方安装中的 `build_service()`。本地验收驱动在同一个 `_browser_transaction()` 中依次调用官方 `_await_gate_clear()`、1200 ms 的 `sleep`、`_snapshot_locked(tab="work")`，校验文章身份与内容后沿用官方 `_publish_page()` 发布捕获；事务释放后本地 `page2md`。未修改产品源码或替换方法。

## 2. 两次动作分别记账

| 流程 | 实际结果 | 配额 |
|---|---|---|
| 前一次公开 `page_read`，用户随后说明忘记点击 | 等待 10085 ms，`terminal=timeout/reason=verification_timeout/stage=wall/waited=true`，未发布文献 | 285→284，1 次导航 |
| 用户要求重新唤醒现有验证页 | 等待动作执行 10076 ms，返回 `ran=true/cleared=true`，接着抓到文章 | 284→284，0 次导航 |

第二次调用侧计时 10.110 秒。用户随后明确确认：**“是，我手动完成了验证”**。因此该样本归为人工完成，而非页面自然自清；没有记录人点击的精确时刻，不能从总耗时推断点击延迟。

## 3. 抓取和转换证据

| 检查 | 结果 |
|---|---|
| 文章标题 | A chemotactic microrobot with integrated iridescent surface for optical-tracking |
| URL 身份 | 与指定 ScienceDirect 文章路径一致 |
| 页面声明 DOI | `10.1016/j.cej.2023.144222`，匹配 |
| 内容判定 | `status=ok`，prose_words=5353，prose_paragraphs=8 |
| 拦截词检查 | blocking_hits=0，paywall_hits=0 |
| navigation_id | `d7666b98-fa89-48a7-b79d-a7df219cf631` |
| tab_id | `1244772760` |
| MHTML | 2,915,487 字节，留存副本哈希一致 |
| page2md | `status=ok`，engine=`sections` |
| Markdown 覆盖诊断 | source_words=12314，extracted_words=7917，ratio=0.643 |
| 结构抽查 | 包含 Introduction、制备/加工/表征等方法小节、结果小节及 Conclusions |

MHTML SHA-256：`a31507362671bee3f00a13385f71985b29a66ebec36c6ef4c27e50757fa63ce6`。

转换回包 `bytes_md=54988`；实际文件为 55178 字节。两者分别记录，不把回包字节数等同于磁盘文件大小。正文判定器的 5353 词与转换覆盖诊断的 7917 词采用不同范围，也不等同于人工逐字完整性检查。

转换已告警：18 个公式由 MathJax 渲染为图形，页面没有相应 MathML，Markdown 未得到对应 LaTeX；未启用 OCR。Markdown 一级标题为 `# page`。本次不宣称标题、公式或全文逐字保真，也不据这一内部 snapshot 流程推断公开 `page_read` 的元数据行为。

## 4. 收尾与验收边界

- 结束后 `browser_busy=false`、`browser_lock=free`、`browser_lease.state=free`；余额 284，cooldown_until=null。
- `status.last_job` 仍保留前一次公开读取的 timeout，符合本次没有启动新的公开 `page_read` 任务这一事实；没有把旧任务结果改写为成功。
- 已覆盖：纯官方等待动作、用户确认的人工放行、随后同一事务内抓取现有页面、文章身份和正文检查、MHTML 留存、离线转换、无新增导航及配额、正常释放锁。
- 尚未覆盖：**单个公开 `page_read` 调用内人工放行后直接续抓**、自然自清、`bridge.timeout` 的迟到回执、enforce 模式及旧代续体围栏。
- 已停止访问站点。本报告只整理留存证据，没有再次访问补样本；未主动修改产品代码。

## 5. 证据位置

运行证据目录：`C:/Users/xuhui/AppData/Local/scholar-search/verification/2026-11-27/wake-manual-0.14.57-ed6ec3b0/`。

- `acceptance.json`：官方校验、前后 status、等待结果、动作审计、文章判定、配额、用户确认与离线检查。
- `capture/page.mhtml`：本次捕获的留存副本。
- `converted/page.md`、`converted/meta.json`、`converted/index.json`：离线转换产物。
- 正式捕获：`C:/Users/xuhui/AppData/Local/scholar-search/pages/A-chemotactic-microrobot-with-integrated-iridescent-surface-ae7b52ea/page.mhtml`。
- 前一次未点击样本：`C:/Users/xuhui/AppData/Local/scholar-search/verification/2026-11-27/manual-0.14.57-20fcd0f5/acceptance.json`。
- 验收驱动：`work/scratch/wake-manual-verification-0.14.57.py`。不要为复查本报告再次运行；只读留存证据即可。
