# wensu 导航、人工验证、加载观察与网页抓取改造方案

日期：2026-11-27，Asia/Shanghai。评审基线：仓库 `0efccca`，版本 0.14.59。方案状态：待实施；本轮仅设计评审，没有修改产品代码、安装新版本或访问出版社网页。

## 结论

推荐采用**不扩权限的分阶段方案**：导航只负责到达目标；验证单独交给用户；用标签页元数据选择第一次捕获时机；以实际捕获内容判断正文是否完整。加载观察预算到期后，在安全条件成立时仍发起第一次捕获；捕获自身到期则记录“结果未确认”，不能据此推断网页没有全文。

先建立捕获阶段、身份、迟到结果和总预算契约，再替换固定的 1.2 秒等待。暂不增加 `scripting` 或全站 host 权限，不把延长到 120 秒作为主要修复。

对用户保留两个验收项：**点击机器人验证后是否进入文献网页；完整全文获取成功或失败**。不新增机构权限识别功能。以下阶段、原因、回执等字段用于实现和诊断，不增加面向用户的判断负担。

## 对现有草案的必要修正

评审输入为同目录的 [prompt-for-gpt.md](D:/Python/DeepSeek/DateWork/scholar-search/work/tasks/2026-11-27-lease-receipt/prompt-for-gpt.md) 与 [plan-readiness.md](D:/Python/DeepSeek/DateWork/scholar-search/work/tasks/2026-11-27-lease-receipt/plan-readiness.md)。早期租约 brief 属历史背景，已完成的身份、锁和回执机制沿用。

| 草案中的说法 | 本方案修正 |
|---|---|
| 3 MB 页面生成 MHTML 曾需要超过 17 秒 | 留存证据是调用在约 17 秒后超时，没有成功生成时间；不能认定卡点是浏览器生成 MHTML。0.14.59 的 60 秒预算也尚不能证明修复成功 |
| complete 加状态静默等于加载完成 | 只能叫“适合尝试捕获的候选状态”，不能证明 DOM、正文或图片完整 |
| 长连接或轮询必然使 tabs 状态一直变化 | 不能这样推断；它们可能根本不产生新的 tabs 状态变化。这里观察的是标签页元数据，不是网络静默 |
| 任意路径至少抓一次 | 只对身份有效、未检测到风险、未取消且通道可用的读取成立；已知验证未解除时必须零次 |
| 至少抓一次就能保证超时前有文件 | 只能保证发起尝试；saveAsMHTML 可能拒绝或始终不返回 |
| 一直未就绪，抓完仍返回 stage=ready/timeout | 就绪预算耗尽是观察事实。捕获成功则最终仍为 publish，超时标记放在 readiness 证据中 |
| snapshot 参数加 wait_ready_ms 就完成分层 | 把观察和捕获塞进同一个长 RPC，会再次混合预算。建议拆成同一动词的观察与捕获模式 |
| 单次请求预算 120 秒 | 当前 native host 拒绝超过 60000 ms 的请求。必须拆 RPC 或另行变更协议，不能只改常量 |
| DOM 探针能使早抓风险接近零 | DOM 稳定也不能保证异步正文、折叠正文或延迟资源完整；只能增加证据 |

前轮成功捕获与本轮超时事实均保留，不据此认定版本回归或网络是直接原因。设计必须能解释这些结果，而不是预先选定一个根因。

## 一 就绪判定与捕获触发

### 证据分为三层

1. **浏览器层**：tab.status、tab.url、tab.title 及 onUpdated 的相关变化；只决定何时值得尝试。
2. **捕获层**：API 是否返回、字节是否收齐、身份是否一致、文件是否完整落盘。
3. **正文层**：正确文章是否包含完整主文。仅有摘要、少量文字或无法证实完整时，最终全文结果为失败。

Chrome 将 status 定义为标签页加载状态，url 为主框架已提交地址；这些字段没有“正文完整”的保证。onUpdated 也不是 DOM 或网络请求观察器。[Chrome Tabs API](https://developer.chrome.com/docs/extensions/reference/api/tabs)

### 推荐的候选状态

worker 在导航发出前注册该 tab 的观察，绑定现有 job/operation/tab/navigation/worker 身份。只在 `status`、`url`、`title` 等相关字段变化时重置稳定窗口，收藏、音频等无关更新不重置。

首次观测到的 complete 可能仍属于导航前的文档。必须结合本次发出后的 loading/URL/完成事件等证据建立导航观察边界；不能给旧 complete 换一个新 navigation_id 就视为新页面。元数据不足以确认同 URL 的刷新或文档替换时，诚实保留不确定，并靠捕获身份校验限制发布。多次 goto 只绑定最后一次已确认导航；不在本轮启用私有导航补丁。

满足以下条件时给出 candidate：目标 tab 存在；url 为有效 HTTP(S) 文章候选地址；未观察到验证或已知拒绝信号；status=complete；至少两次元数据观测一致，观察跨度不少于 750 ms，期间相关 onUpdated 没有改变这些字段。750 ms 是初始去抖参数，不是全文加载用时；必须用假时钟覆盖边界，并可在灰度数据中调整。

状态为 loading、字段缺失或元数据继续变化时给出 observing。不能把缺失值当作 complete，也不能把标题变成论文名当作完整正文。只使用提示词限定的元数据即可实现；如果后续采用 pendingUrl，必须作为额外可用信号协商，不能偷偷变为旧构建的必填条件。

观察结束有四种出口：candidate；已知风险；目标丢失/身份变化；观察预算用尽。只有 candidate 和“预算用尽但安全条件仍成立”触发首次捕获，后者明确标记 trigger=readiness_budget_exhausted，而非 ready=true。

### 可能误判及兜底

| 情况 | 元数据会怎样误导 | 兜底 |
|---|---|---|
| SPA 在 complete 后继续插入正文 | 过早成为 candidate | 看第一次捕获内容；正文不足时允许一次有界补看，仍不足则失败 |
| 广告、图片拖住加载，正文其实已完整 | 长时间 observing | 观察预算用尽后尝试捕获，按实际正文裁决 |
| 标题先就绪，正文尚未出现 | 看起来像论文 | 标题不作为正文判据 |
| 验证标题不在已有规则里 | 无法在捕获前识别 | 检查首份捕获；一旦识别风险立即停止并丢弃，禁止第二次捕获或发布 |
| 用户换文章、tab 被替换、worker 重建 | 观察属于旧页面 | 废弃旧观察；重新核对身份，不能静默跟随新页面抓取 |
| 元数据始终不变但正文延迟超过两次捕获 | 两次都可能太早 | 明确失败；当前权限下不能保证自动等到正文，允许用户明确确认后发起新的只读恢复流程 |

不声称观察能证明 HTTP 200，也不声称当前权限能在捕获前发现所有 403/429。已有明确拒绝信号仍立即按规则停止和冷却；无法观测到的 HTTP 状态保持未知，不从 complete 推导。

## 二 推荐流程与抓取次数不变式

### 正常流程

1. 核对官方运行版本、能力、额度、锁及目标身份，绑定唯一工作 tab。
2. goto 正常访问一次，保留导航回执。goto 的返回只确认导航事实及当时元数据，不承担正文就绪判定。
3. 若观察到验证，进入现有人工等待。用户解决前只观察，不导航、不捕获、不代点。10 秒到期则保留页面和可恢复信息，结束当前调用；没有其他未决浏览器操作时释放锁，不因用户尚未点击而长期占用。恢复时重新准入并核对原目标。
4. 用户在当前调用内完成验证，或之后明确确认进入文章页时，开始/恢复加载观察。恢复必须绑定原目标，禁止隐含 goto。
5. 使用 snapshot 的观察模式等待 candidate，或到达观察预算。调用前再核对风险、tab 和导航身份。
6. 发起第一次物理 saveAsMHTML；收齐字节后暂存、校验身份及内容。
7. 若正文完整，发布一次。若是明确不足的正文样本且没有风险，可再观察一次并至多捕获第二次；API 仍未结束、传输失败或验证仍存在都不能触发第二次物理捕获。
8. 第二次必须绑定相同 tab 和目标，独立校验。完整结果优先；否则只留本次可核验的不足证据，全文结果为失败，不将等待超时改写成网页没有全文。

捕获只能归入当前读取会话。用户显式请求新访问是新会话；人工恢复当前读取则继承原会话的捕获计数。原调用已返回的 timeout 保持不变，恢复调用可以给出新结果并引用原调用，不能事后篡改旧回包。

### 可写成测试的不变式

| 编号 | 断言 |
|---|---|
| I1 | 每个读取会话的物理 saveAsMHTML 调用次数为 0、1 或 2；观察、状态查询和读取分块均不增加次数 |
| I2 | 已知验证未解除、已知拒绝、取消、能力不符、tab 丢失或身份冲突时，不发起首次捕获 |
| I3 | 持续有效且无风险的会话，在观察得到 candidate 或预算用尽后，必须发起第一次捕获；不能只等到观察超时就返回 |
| I4 | I3 保证 attempt_started，不保证 artifact_available；API 永不返回的 fixture 必须允许无文件退出 |
| I5 | 第二次仅在第一次已结束、已有可分类字节且正文不足时发生；第一次结果未确认时不得并行启动第二次 |
| I6 | 观察和人工恢复不执行 goto/reload/create，不增加导航额度；人工恢复不能刷新掉已经放行的页面 |
| I7 | 任意捕获发现验证或拒绝后立即停止；已知墙通常零次捕获，事后才识别的墙可能已经尝试一次，但发布次数始终为零 |
| I8 | 任何迟到结果只能更新原 operation 的事实，不能填入新 waiter、改写其他会话文件或成为下一篇结果 |
| I9 | candidate、观察预算耗尽、文件存在，都不能单独令 full_text=true |
| I10 | 最终发布至多一次，文件 SHA-256 与回包一致；第二次不足或失败不能覆盖已经确认完整的捕获 |

第二次观察仍然只有元数据，不能保证覆盖任意 SPA 延迟。不要把“最多两次”描述成“绝不早抓”的证明。

## 三 三类预算与回包语义

以下数值是建议初始配置，属于工程取舍，不是从 17 秒样本推导出的正确加载时长。

| 预算 | 建议值与起点 | 到期行为与技术回包 | retryable |
|---|---|---|---|
| 人工验证 | 保留现有 10 s；前置窗口的结果可观测后开始 | 最近证据仍为验证：terminal=timeout、stage=wall、reason=verification_timeout、waited=true；页面保留 | false，等待用户明确确认，不自动再访问 |
| 首次加载观察 | 30 s；验证解除、身份有效后开始累计 | observation=budget_exhausted；安全条件成立仍发起首次捕获。之后成功则 stage=publish，不能让旧观察超时盖掉成功 | 不单独触发重试 |
| 第二次加载观察 | 至多 10 s，只使用一次，不重置首次计数 | 到期可触发已获许可的第二次捕获；仍不能伪称 candidate | 不单独触发重试 |
| 单次捕获与传回 | 总计 60 s；从物理捕获发起到字节收齐，跨分块共享余额 | 发出后无确认：terminal=timeout、stage=capture、reason=capture_unconfirmed、artifact_available=false；结果未知不等于 API 已失败 | false；先追问原操作，不另发捕获 |

观察阶段结束不需要增加 stage=ready：在 evidence.readiness 中保留 state、trigger、elapsed_ms、budget_exhausted、last_tab_status。最终 stage 继续使用既有 navigate/wall/capture/identity/publish 等语义。这样可避免“已有完整文件但终态还写就绪超时”的矛盾。

捕获明确被浏览器拒绝时可记录 capture_failed；传输中断且已知物理捕获完成时记录 transfer_incomplete，并允许从同一个 capture_id 续传。预算用尽且底层是否结束未知时只能记 unconfirmed。所有路径对用户都可按本次是否取得完整正文映射成功/失败，但诊断不得声称网页不存在或没有全文。

每次分块请求的 deadline 取“该阶段剩余时间”与单 RPC 上限的较小值，禁止每个块重新获得 60 秒。native host 当前接受的单 RPC 上限为 60 秒；适配器 socket 额外保留已有回包余量。观察 RPC 建议不超过 35 秒；捕获首个 RPC 为总预算预留通信余量，具体拆分由假时钟用例固定。

若需要单次捕获逻辑预算超过 60 秒，另做 start/pending/status/collect 的异步协议：每个 RPC 仍不超过宿主上限，查询不启动新 saveAsMHTML。不要直接发送 timeout_ms=120000。首版不启用这个扩展。

上层 MCP/HTTP/客户端的总 deadline 必须覆盖各阶段累计；支持最坏路径的客户端建议协商约 240 秒外层上限。支持不了的客户端要先返回带原操作身份的未完成结果并允许只读恢复，不能让外层先断开却把底层当作已取消。长外层上限不是等待满额才抓的理由。

这三类预算不能互推：用户点击速度不能代表正文加载速度，页面 candidate 不能代表 MHTML 生成速度，文件大小也不能证明生成阶段的耗时。分别记录阶段用时，只调有证据的那一层。

## 四 方案比较与权限建议

| 方案 | 成本 | 收益 | 失效条件与建议 |
|---|---|---|---|
| 维持固定 sleep，只扩大预算 | 最低 | 容忍部分慢捕获 | 仍早抓、仍混淆阶段，不推荐作为改造方案 |
| 元数据观察加内容裁决 | 中等；新增观察模式、预算与回执 | 保持现有权限，覆盖慢加载并保证有界尝试 | 看不见 SPA 正文进度；推荐先实施 |
| scripting 加 activeTab | 中等；需用户调用扩展入口授权当前 tab | 可临时只读 DOM，授权面小 | MCP 命令本身不自动授予 activeTab；需要用户额外操作，不适合默认无人干预路径 |
| scripting 加按需出版社 host 权限 | 较高；逐站授权和规则维护 | 直接观察目标页正文、DOM 稳定与滚动加载状态 | 仍不保证完整，域名/iframe/页面结构变化会失效；仅作为后续可选方案 |
| scripting 加 https://*/* | 最高；持续全站访问面、权限提示及审计成本明显增加 | 使用范围最广 | 超出当前两渠道边界，不能证明收益值得范围扩大；不推荐 |

执行脚本需要 scripting 加相应 host 授权，activeTab 可在用户明确调用扩展入口时临时授权。点击网页中的验证码不是调用扩展入口，不能据此认为自动获得 activeTab。[Scripting API](https://developer.chrome.com/docs/extensions/reference/api/scripting)、[activeTab](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab)

扩权限时必须另有 ADR，说明新权限、用途、站点范围、撤回和滚动升级行为；逐站授权优先于全站授权。具体权限警告、扩展被停用或需重新授权的 UI 行为要以目标 Edge 版本安装验证，不能一概声称“必然重装”。即使扩权限，也不将 DOM 稳定当作完整全文的证明。

## 五 goto 与点击书签的区别及最小实验

服务器看到的是请求、重定向链及会话状态，不能直接看到“书签按钮”这个 UI。请求可能在 Fetch Metadata、Referer、缓存使用及重定向上下文上不同；同一个 profile、相同 URL 并不能先验保证这些值都相同。

Fetch Metadata 草案规定 Sec-Fetch-User 表示导航是否由用户激活触发；书签等浏览器 UI 导航属于直接用户发起的情形，Sec-Fetch-Site 通常按 none 处理。草案同时单列扩展发起请求，允许浏览器结合扩展权限处理，因此不能预先断定当前 Edge 的 tabs.update 一定缺某个头或必然被判为爬虫。[Fetch Metadata 草案相关规则](https://www.w3.org/TR/fetch-metadata/#sec-fetch-user-header)

tabs.update 的公开参数没有“设成书签导航”、指定这些请求头或制造真实用户激活的开关。把窗口前置、添加随机等待或模拟页面点击都不能提供这种保证；本方案保持普通导航，不改写请求头来伪造人工来源。[Tabs update 参数](https://developer.chrome.com/docs/extensions/reference/api/tabs#method-update)

**最小实验只访问回环地址，作为实施者的独立实验，不进入真实文献验收：**

1. 本地 HTTPS 回显服务提供 /seed、/article、/redirect 三个无外部资源端点；使用已可信的本地证书，不绕过证书警告。若只有 HTTP 回环服务，须先验证该 Edge 在该上下文是否生成 Sec-* 头，不能将头缺失归因为某种导航方式。
2. 两种方式都从同一 profile、同一工作 tab、同一 /seed 起点进入相同 /article：A 由用户点击书签，B 由扩展正常 tabs.update。顺序 AB/BA 交叉，分别比较直达和一次本地重定向。端点返回 no-store，不清全局浏览器数据。
3. 只记请求方法、路径、Sec-Fetch-Site/Mode/Dest/User、Referer 是否存在及其本地来源、重定向跳数；不记录真实 Cookie、账号或外部浏览历史。固定 Edge/worker 版本，记录重复结果。
4. 断言：外部请求数为零；两组浏览器起点、URL、缓存响应策略一致；除导航入口外变量固定。得到的差异只代表该浏览器版本和本地条件，不能推导它就是出版社验证触发原因。

当前自动导航白名单不含回环实验源。不得为实验放宽生产白名单：使用单独的测试 harness/开发扩展，并复用同一个导航函数；生产发行物权限与名单保持原状。实验结果形成对照表即可，不进入“如何绕过验证”的实现。

开发 harness 只在自身测试策略中允许回环目标，不给扩展增加该目标的 Chrome host_permissions；否则扩展权限本身就会成为 Fetch Metadata 的混杂变量。确需比较“有 host 授权”时另列实验组，不混入上述两组。

## 六 跨层落点、实施阶段与验收

### P0 冻结契约及观察语义

新增 readiness/capture ADR 和协议小节，定义 snapshot(mode=observe) 为零字节元数据观察、默认模式仍为捕获、已有 token/offset 仍只读取同一捕获。mode、observe_ms、期望身份等参数必须闭合校验，观察模式与 token/offset 互斥。

新增 features.readiness_observe=1 与 features.capture_receipts=1，均为拟议字段。worker、host info、适配器、内核握手均透传；未协商不得发新参数。默认 snapshot() 的 MCP 签名可以不变，由内核编排观察；用户恢复则需新增明确的 resume_job_id 参数，禁止与 refresh=true 同用。

捕获回执沿用现有宿主 operation 账本和只读查询实现，以 action=snapshot 区分操作；capture_issued 独立于 navigation_issued，不能混用。首版可由内部查询读取原操作状态；若公开查询入口或现有 navigation_status 的适用范围变化，必须同步 MCP 描述和 schema，不能只在文档里声称已有 capture 查询能力。

采用独立观察模式而非 probe_only 混合布尔字段，避免“观察模式意外生成 MHTML”。不新增浏览器动词，但仍需 ADR 和跨层契约测试，因为动作参数与行为发生变化。

### P1 捕获身份、预算与迟到结果

在现有 operation_id 体系下补 capture_id、attempt_index、capture_issued 三值事实和阶段事件；状态可查询，但共享账本只记元数据，禁止写正文或 MHTML。捕获 token 仅在该 worker/操作范围内有效。

至少记录 capture_started、blob_ready、bytes_ready、transfer_complete、staged、published，以及各阶段耗时。所有 async 续体检查原 tab、worker epoch、operation 和 fence；捕获前后各取一次元数据，变更时拒绝串页。只靠 worker 最后一次 goto 的 navigation_id 不足以证明用户没有手动导航，仍需页面身份校验。

pageCapture API 只提供生成 MHTML 的 Promise，没有取消参数；逻辑超时不能当作底层已停止。[PageCapture API](https://developer.chrome.com/docs/extensions/reference/api/pageCapture) 对发出但未确认的捕获保留 in-flight 标记，禁止新物理捕获；允许查询原操作。没有取消确认时不以 TTL 自动放行；无法恢复时提示用户采取明确的外部操作，不能自动重启浏览器。

0.14.59 将 snapshot 超时概括为可重试的规则应在新契约中收紧：免费不代表可安全重复。仅原捕获已结束后的同 token 续传、或已证明未发出的调用才可声明可恢复；风险分支始终禁止自动重试。timeout 原因使用结构化字段，避免按异常文案猜测。

### P2 元数据观察与内核编排

worker 增加独立观察 helper；goto 在最后一次实际导航后建立观察身份，现有等待上限只报告导航观察结果。snapshot 观察模式不调用 pageCapture、不发网络请求。内核移除固定 sleep 作为触发依据，按本文流程串行执行。

snapshot 的观察及捕获前检查统一接收内核现有的 halt_titles 等规则参数，不在 worker 维护另一份出版社判墙词表；这些参数也必须加入 snapshot 的闭合校验。当前 snapshot 先生成字节再判断标题，需把能由元数据确认的验证前置；只能从内容发现的验证则维持捕获后立即丢弃、停止的行为。

正常 page_read、URL-only、用户手动放行后的恢复以及公开 snapshot 都调用同一套“绑定→观察→捕获→校验”入口。恢复先校验现有页，不以 DOI 缺省为由重新导航；第一次和第二次都传同一个明确 tab_id，不回退到别的活动 tab。已知不足内容不能命名为 still_rendering 的确定事实，建议内部改为 insufficient/unknown。

最终 stage 显式保留实际终止阶段；当前 `_page_stage` 会将泛 status=timeout 映射到 navigate，必须避免它把 capture 超时误归为导航。对外 terminal 枚举维持现状；新增细节放在 evidence，而不是不断增加用户可见状态。

### P3 灰度、公开恢复及真实验收

先观察模式只记证据，不改变触发；离线全绿后，仅在完整新协议链路启用新触发。人工恢复绑定旧会话的目标和捕获计数，新调用保留独立终态，不能把旧 timeout 改成成功。只有在确认旧操作没有未决捕获时，才发下一次物理捕获。

灰度开关在内核，必须区分“可退回旧观察策略”和“存在未决捕获”。后者不能靠关开关绕过。回滚只影响新空闲会话，保留已发 operation 的回执与身份；不清配额、冷却、账本或旧文件，不关闭用户浏览器。旧链路缺能力时可继续明确标识的旧行为，但不能宣称执行过新观察；恢复或异步捕获等新功能必须拒绝，不得静默重新 goto。

### 文件与函数落点

| 位置 | 需要同步的职责 |
|---|---|
| [worker](D:/Python/DeepSeek/DateWork/scholar-search/extension/background-0.14.59.js) 的 waitComplete、goto、snapshot、await_gate_clear | 新版本 worker 文件，观察 helper、模式分派、捕获阶段、身份与原操作恢复；不改 content script 覆盖面 |
| [params.py](D:/Python/DeepSeek/DateWork/scholar-search/src/scholar_search/core/params.py) ALLOWED_KEYS/validate_params；[contracts.py](D:/Python/DeepSeek/DateWork/scholar-search/src/scholar_search/core/contracts.py) | mode/预算/身份闭合校验；观察与分块互斥；同步 Action 与状态字段类型 |
| [native-host/main.py](D:/Python/DeepSeek/DateWork/scholar-search/native-host/main.py)；[bridge policy](D:/Python/DeepSeek/DateWork/scholar-search/src/scholar_search/adapters/bridge/policy.py) | 保持单 RPC 60 秒边界；实际安装的校验模块必须接受协商后的新参数 |
| [bridge host](D:/Python/DeepSeek/DateWork/scholar-search/src/scholar_search/adapters/bridge/host.py) request/_wait；[bridge adapter](D:/Python/DeepSeek/DateWork/scholar-search/src/scholar_search/adapters/bridge/__init__.py) _send/execute | 原捕获回执、迟到归档、features、剩余 deadline 和 operation_id 传递；不把迟到字节交给新 waiter |
| [service.py](D:/Python/DeepSeek/DateWork/scholar-search/src/scholar_search/core/service.py) _read_page/_await_gate_clear/_snapshot_locked/_collect_chunks/_page_stage/_page_evidence | 共用编排、捕获计数、三预算、身份及总分块预算、最终回包证据 |
| [server.py](D:/Python/DeepSeek/DateWork/scholar-search/src/scholar_search/server.py) page_read/snapshot/_payload/_retryable | 恢复参数、完整字段透传、timeout 与可恢复语义；不依赖错误前缀猜发出状态 |
| [lease.py](D:/Python/DeepSeek/DateWork/scholar-search/src/scholar_search/core/lease.py) 与 [protocol-lease.md](D:/Python/DeepSeek/DateWork/scholar-search/docs/protocol-lease.md) | capture 原操作状态与字段白名单；已有 observe/enforce 模式如实保留，不能把观测模式宣称为强制隔离 |
| [兼容文档](D:/Python/DeepSeek/DateWork/scholar-search/docs/compatibility.md)、[批量 skill](D:/Python/DeepSeek/DateWork/scholar-search/skills/scholar-batch-read/SKILL.md)、[单篇 skill](D:/Python/DeepSeek/DateWork/scholar-search/skills/paper-page/SKILL.md) | 未决时暂停、人工确认后零导航恢复；最终仍只输出完整全文成功/失败 |
| [schemas/tools.json](D:/Python/DeepSeek/DateWork/scholar-search/schemas/tools.json)、[DSH bundle](D:/Python/DeepSeek/DateWork/scholar-search/packages/dsh-wensu/package.json) | schema 由 dump-tools.py 生成，不手改；四线版本同步，MCP 重连后才能验收新签名 |

新增 evidence/错误字段必须同时进入 adapter outcome、ActionError、server payload、读取 evidence、last_job 的对应白名单；不能再次出现“文档要求查询 id，但该 id 没传到调用方”。协议实现方要以实际字段筛选点为准逐项查证。

## 七 验证矩阵与实施者命令

以下是拟实施后的验收要求，本轮未运行新测试，也不将方案写成已验证实现。

| 阶段 | 离线断言 | 灰度与回滚 |
|---|---|---|
| P0 | 非法 mode、超界预算、混合 observe/token 被拒；混版本不发送新参数；未知 issued 为 null | 新行为关闭；可单独撤回未启用字段 |
| P1 | 假时钟捕获 20 s 成功；永不返回变成 unconfirmed；分块累计不重置预算；迟到不串请求；查询不创建新捕获 | 先只记录；未决操作不能随开关丢弃 |
| P2 | complete 后 SPA 延迟、持续 loading 但有正文、标题变化、tab 替换、已知墙、内容中才发现墙；逐条满足 I1—I10 | 空闲会话启用新触发；回滚不改变已发请求 |
| P3 | 用户在 10 s 内或之后放行的恢复、URL-only、实际无全文、正确完整正文；恢复无 goto、计数不重置 | 用户指定单篇验证，不制造墙；失败保留证据 |

拟新增 `tests/unit/test_page_readiness.py`、`test_capture_lifecycle.py`、`test_readiness_contract.py` 与相应真 worker/假 Chrome API 回放。必须测实际分支、调用次序和时间推进，不能只断言常量大于某个秒数。frame 内 Blob、数组、token 状态需用真实 worker 回放；保存 MHTML 的浏览器实现仍需本地页面和真实样本核验。

现有 `test_snapshot_timeout.py` 中“任何捕获超时都可重试”的断言需按 issued/已完成/未确认三类更新，不能保留旧断言再为新语义开后门。用单调时钟计算各阶段 elapsed 和剩余时间，墙钟只用于审计展示，系统校时不能增加预算。

实施者从仓库根执行的检查命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_readiness_contract.py tests/unit/test_capability_contract.py
.\.venv\Scripts\python.exe -m pytest tests/unit/test_capture_lifecycle.py tests/unit/test_snapshot_timeout.py tests/unit/test_bridge_late_reply.py
.\.venv\Scripts\python.exe -m pytest tests/unit/test_page_readiness.py tests/unit/test_wall_early_exit.py tests/unit/test_page_read_open_tab.py
.\.venv\Scripts\python.exe scripts/dump-tools.py --check
.\.venv\Scripts\python.exe scripts/release-check.py
```

真实验收维持用户限定的两项：用户点击验证后是否进入文献网页；随后工具是否取得完整主文。正文不足或未获得正文均为失败；“有文件”“有摘要”“字数够”不能单独判成功。身份、章节覆盖、正文是否截断作为内部核验依据，不把它们扩展成用户必须诊断的机构权限问题。

首轮先用无外部资源的本地慢页面验证时间与触发，再对用户指定文章正常访问一次。自然出现验证时由用户点击；遇已知 403/429 立即整批停止。此次设计评审不额外访问网站补样本。

## 八 风险登记

| 风险 | 影响 | 处理与仍有的限制 |
|---|---|---|
| 元数据不可见的延迟正文 | 早抓或漏正文 | 内容裁决、最多一次补看；承认当前权限的证据上限 |
| 以预算耗尽替代内容判定 | 错报网页不存在或无全文 | 分开 elapsed、trigger、outcome；最终用户失败仅表示本次未取得完整全文 |
| 物理捕获未结束却释放资源 | 两次捕获重叠、迟到串页 | 原操作回执、in-flight、旧代隔离；没有取消确认不按 TTL 解锁 |
| 用户手动导航、同 URL 多 tab | 抓错文章 | 显式 tab 绑定，捕获前后核对，内容身份校验 |
| worker 或 native host 重建 | token、观察历史、内存字节丢失 | epoch 不匹配后诊断；不认为握手正常就能续旧 token |
| 每块重获完整超时、token 过期 | 总时间无界或中途丢文件 | 总 deadline、token 生命周期覆盖传输、明确完成清理；保留尺寸与内存上限 |
| MHTML 内存及帧限制 | 重页拖垮 worker 或协议 | 保留分块和体量限制；不能改为单帧整页传输。Native messaging 两方向上限并不相同，[官方协议](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging#native-messaging-protocol) |
| MV3 生命周期 | 长操作丢状态 | 原生连接可延长存活，但仍需支持异常终止，不能依赖永久全局 Map。[生命周期说明](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle) |
| 抓取触发懒加载资源 | “零显式导航”被误写为“绝无网络活动” | 只承诺不由观察/控制主动导航；本地回显核对 pageCapture 的实际行为，不能保证页面自己的脚本停止请求 |
| 日志泄露或正文进入共享账本 | 内容与会话暴露 | 仅标识、体量、耗时和枚举；URL 临时参数脱敏，正文留 home 的捕获区 |
| 滚动升级参数/字段漏层 | 新动作被拒或诊断丢失 | features 协商、跨层契约、安装产物检查和 MCP 重连 |

## 九 明确不做的事

不使用 CDP/debugger；不自动识别或代点验证；不更换 IP/代理；不并发访问或捕获；不绕过安全、登录或访问限制；不新增机构权限识别；不下载 PDF/CAJ 或自动写文献库；不以固定 sleep 作为正文就绪证据；不通过增大预算宣称已修复；不为制造验证反复访问；不把用户页面判断交给 Computer Use。

## 十 需要确认的决策点

1. **权限路线**：推荐首版维持现有权限；只有真实样本证明不足后，才另审按站点授权的 DOM 观察。
2. **初始预算**：推荐人工 10 s、首次观察 30 s、第二次观察 10 s、每次捕获及传回总计 60 s；允许调参但不改变到期语义。
3. **超时恢复**：推荐原操作未确认时仅查询、不再发捕获；新增明确的人工恢复参数，不能用“再调用一次就自动导航”代替恢复。
4. **完整性口径**：推荐只在正确文章的完整主文有可核验证据时判成功；不足或无法确认完整则失败，内部保留原因，不扩展用户验收类别。
5. **实施范围**：推荐先 P0—P2 的契约、捕获生命周期和元数据观察，再 P3 真机验收；不把 120 秒异步捕获或全站权限捆入首版。
