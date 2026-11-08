# 故障台账

只记真实发生的故障：现象 → 根因 → 修复 → 是否可借鉴避免。新故障追加在顶部。

## 2026-11-08 WoS 捕获脚本匹配错端点，`wait_for` 超时被误判成"没注入"

- **现象**：WoS 检索的每个动作都成功（`goto` 1823ms、`wait_for` 2ms、`type` 5ms、`click` 323ms），
  只有末尾的 `wait_for #wensu-wos-capture[data-ready='1']` 等满 6 秒超时，报 `no page payload`。
- **根因**：`capture.js` 只匹配 `/api/wosnx/core/runQueryGetRecordsStream`（用户手动点排序时看到的端点），
  而点「检索」按钮发的是 `/api/wosnx/core/runQuerySearch`。两个端点都返回完整记录，只是名字不同。
- **排查关键**：给 capture.js 加两个可读证据——`html[data-wensu-capture="loaded"]`（证明脚本在页面世界
  真的跑起来了）和 `html[data-wensu-seen]`（页面实际请求过的 path，query string 已剥离、不含 SID）。
  一次探测就把"没注入"与"端点不匹配"这两种可能分开，省掉了反复改代码重试。
- **修复**：匹配前缀放宽到 `/api/wosnx/core/runQuery`；解析器一行没改就吃下了 `runQuerySearch`
  （实测 20 条 / 243 KB / 含摘要）。
- **教训**：① 不要用 DevTools 的 Size 列估算字段覆盖度——那是 gzip 后大小，38.6 KB 解压后 243 KB，
  我据此推断过"装不下摘要"，错了两次；② 注入到页面世界的脚本必须自带"我跑起来了"的证据，
  否则失败只能靠猜；③ 站点可能有多个等价端点，按前缀匹配而不是全名。

## 2026-11-08 `pip install --upgrade` 卸载成功、换 exe 失败，包被删空

- **现象**：升级 0.4.2 → 0.5.0 时 pip 报
  `ERROR: Could not install packages due to an OSError: [WinError 32] 另一个程序正在使用此文件:
  'd:\python\python314\scripts\wensu.exe'`。随后 `import scholar_search` 直接 `ModuleNotFoundError`，
  site-packages 里连 `scholar_search` 和 `wensu-*.dist-info` 都没了。
- **根因**：MCP 服务进程（`wensu.exe serve --transport stdio`，PID 19628）正在运行，Windows 不允许
  删除正在执行的可执行文件。pip 的顺序是「先卸载旧版本、再装新版本」，卸载成功了，装载脚本阶段
  失败，回滚也没有把包文件放回来——`pip install --upgrade` **不是事务性的**。
- **影响面**：磁盘上的包消失。运行中的 MCP 进程因为模块已在内存里而暂时工作，但**任何新启动的
  host 都会崩**：扩展一旦重载就会断桥，症状会看起来像「扩展坏了」。
- **修复**：绕开 `wensu.exe`，把 wheel 直接解压进 site-packages——
  `Expand-Archive <whl> → Copy-Item x\scholar_search <site-packages>\`，并复制
  `wensu-0.5.0.dist-info`。之后 `pip show wensu` 为 0.5.0，`import`、CLI、`native-host\main.py`
  的导入全部恢复正常。
- **教训**：升级正在运行的 pip 包，要么先停掉占用 `Scripts\<name>.exe` 的进程，要么干脆不解包、
  直接覆盖包目录。不要假设失败会回滚。

## 2026-10-21 代理换证导致 `content_not_ready`，被误判为 MCP 故障

- **现象**：新装环境第一次 `search`，`goto` 成功（约 1.9 s），紧随的 `sleep` 报
  `content_not_ready`。浏览器窗口标题是「隐私错误」。
- **根因**：本机开着 Clash Verge（系统代理 `127.0.0.1:7897`，未开 TUN），`kns.cnki.net`
  被 TLS 中间人换证，Edge 报 `NET::ERR_CERT_COMMON_NAME_INVALID`。错误页上没有内容脚本，
  所以第一个 DOM 动作必然失败。
- **误判点**：`Invoke-WebRequest https://kns.cnki.net/kns8s/search` 返回 200——PowerShell
  不走 WinINET 注册表代理。命令行能通 ≠ 浏览器能通，这一点最容易得出"是 MCP 坏了"的错误结论。
- **修复**：把 `*.cnki.net;cnki.net` 加进 `ProxyOverride` 并用 `InternetSetOption(39/37)`
  广播；持久做法是在 Clash 规则里配 `DOMAIN-SUFFIX,cnki.net → DIRECT`。
- **验证**：同一窗口重新加载知网检索页，`search` 9.7 s 返回 `total=595`。
- **可借鉴**：是。判断"站点是否可用"必须用**浏览器**的证据（窗口标题、错误码），不能用命令行。

## 2026-10-21 年度过滤“触发认证”实为误判

- **现象**：点击 `#btnFilterYear` 后页面出现“手机号认证”，结果表消失，检索返回空页（`total: null`），被当作账号验证门并置 24h 冷却。
- **复核**：用户确认浏览器无弹窗、机构仍登录。保存的页面其实是正常检索页（标题“检索-中国知网”，检索框仍在），所谓认证文案来自页面**常驻的登录面板**（`ecp_loginArea`、`Ecp_top_login_realName` 等，多数默认 `display:none`）。
- **根因**：认证检测用了“正文文本包含关键词”这种宽泛规则，和之前验证码误判是同一类错误。
- **修复**：
  - 改为检测登录弹窗是否**可见**（`#Ecp_top_login_realName` / `#Ecp_top_login_oversea` 的 `display` 与 `getBoundingClientRect().height`）。
  - 年度过滤仍然保持下线：它确实会让结果表消失，行为不可靠，但不构成风控事件。
  - 清除冷却，单次只读检索复验：IPMC 595 条正常。
- **教训**：风控信号必须是“结构性可见证据”，不能是文本包含。

## 2026-10-21 卷期页解析为空

- **现象**：印刷版文章详情 `volume/issue/pages` 全为 null，只有年份。
- **根因**：这些字段不在 `li.top-space` 元数据行里，而在 `.top-first` 的引文行：
  `力学学报 . 2022 ,54 (01) : 184-195 查看该刊数据库收录来源`。
- **修复**：新增 `_TOP_LINE` 正则解析引文行；`source` 取 ` . ` 前段；`li.top-space` 作为兜底。
- **验证**：fixture 回放 + MCP 真机（2022, 54(01), 184-195）。
- **备注**：该页还叠了一条“检测到您的IP已超出使用范围”的横幅，但正文与元数据仍可读；这不是风控页，不触发熔断。

## 2026-10-20 旧链接跳“安全验证”页，检测器漏判

- **现象**：用几天前保存的详情 URL 导航，页面标题变成“安全验证”，解析报 `detail page has no title`；服务层没有返回 `blocked`。
- **根因**：风控只看 URL 和验证码控件，验证页的 URL 不含 `/verify`，标题才是唯一可靠信号。
- **修复**：内容脚本在 `read_html` 时回传 `document.title`；风控命中“安全验证/验证中心”即 `verify_redirect`。
- **可借鉴**：是。参考项目都判断页面状态而不只看 URL。

## 2026-10-20 每次检索都误熔断

- **现象**：MCP `search` 一律返回 `blocked / text_marker`。
- **根因**：风控扫描整页 HTML 文本，命中腾讯验证码 SDK 预加载的隐藏 DOM（`#tcaptcha_transform_dy`，常驻屏幕外）。
- **修复**：改为内容脚本判断该元素是否可见并回传 `captcha_visible`；不再扫文本。
- **可借鉴**：是。cookjohn 明确写了这个隐藏 DOM 的坑。
- **影响**：误报触发了一次 24h 冷却（测试环境手动清除）。

## 2026-10-20 一框式 URL 不触发检索

- **现象**：`defaultresult/index?kw=...` 返回 96KB 检索外壳，`result-table-list` 为 0。
- **根因**：新版页面需要走“输入 + 点击”才发检索请求。
- **修复**：`plan_search` 改为 `goto /kns8s/search → wait_for → type → click → wait_for → read_html`。
- **可借鉴**：是。cookjohn 的流程本来就是这样。

## 2026-10-20 `limit` 不生效

- **现象**：`limit=10` 返回 20 条。
- **根因**：服务层没有截断，直接返回整页。
- **修复**：`service.search` 按 `query.limit` 切片，加回归测试。

## 2026-10-20 翻页“没反应”

- **现象**：`page=2` 返回第一页内容。
- **根因**：两层：计划里根本没实现翻页；补上后又命中了修复前的缓存。
- **修复**：`#PageNext` + 等待 + 读取；缓存键加入包版本。
- **可借鉴**：部分。缓存版本化是通用教训。

## 2026-10-20 计划预算超限

- **现象**：`page=2` 报 `plan budget 135000ms exceeds 120s`。
- **根因**：每个动作都按默认 15s 计，翻页再加 3 个动作。
- **修复**：按动作类型设超时（导航/等待 15s，输入/点击 5s），页码上限 3。

## 2026-10-20 宿主进程秒退，日志为空

- **现象**：Edge 拉起宿主后 Python 立即退出码 1，`host.log` 不生成。
- **根因**：浏览器以**低完整性级别**启动原生宿主，写不了 `AppData\Local`；异常发生在写日志之前。
- **修复**：宿主运行时（`bridge.json`、日志）改到 `%TEMP%\scholar-search`；启动器捕获 stderr 落盘便于诊断。
- **可借鉴**：否。参考项目都不走原生消息。

## 2026-10-20 Edge 不启动 `.cmd` 宿主

- **现象**：manifest 指向批处理时报 “Native host has exited”。
- **根因**：Chrome/Edge 用 `CreateProcess` 直接启动，不经过 shell。
- **修复**：用系统自带 `csc` 编译 4KB 的 `scholar-host.exe` 做管道包装器。

## 2026-10-20 双宿主、回执发错连接

- **现象**：适配器请求超时；有时两个宿主互相覆盖端点。
- **根因**：扩展重复建连；回执统一发到全局 `port`，与请求来源连接不一致。
- **修复**：按连接回执（`onHostMessage(message, channel)`）；宿主侧取消单实例拒绝，改为“一条连接一个宿主”。
- **教训**：单实例检查会把重连挡死，形成“老宿主占端点、新宿主立刻退出”的死锁。
