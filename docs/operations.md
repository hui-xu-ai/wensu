# 运维手册：安装、升级、回滚与排障

面向自己部署和维护的人。只想知道怎么调工具，看 [README](../README.md)。

## 1. 三种安装形态

| 形态 | 适用 | 浏览器资源在哪 |
|---|---|---|
| `pip install wensu`（离线用 `pip install .\wensu-<版本>-py3-none-any.whl`） | 一般用户 | 用 `wensu assets --target <目录>` 导出 |
| `pip install -e ".[dev]"` | 改代码 | 仓库里的 `native-host/`、`extension/`、`schemas/` |
| 部署树 `installations/<版本>/` | 多版本并存、给 MCP 客户端固定路径 | `installations/<版本>/browser/` |

部署树长这样：

```
installations/<版本>/
  venv/                    独立虚拟环境（解释器 + 依赖）
  browser/
    native-host/           main.py launcher.cs install.ps1 + 生成的 scholar-host.exe / manifest
    extension/             background.js content/actions.js manifest.json
    schemas/               record.json tools.json
```

MCP 客户端指向 `installations/<版本>/venv/Scripts/python.exe`，好处是升级时可以并行装新版本、
回滚只改一行路径。

## 2. 状态目录

默认 `%LOCALAPPDATA%\scholar-search`，可用 `SCHOLAR_SEARCH_HOME` 覆盖。
**同一个 HOME 只能有一个活跃部署**，否则配额与冷却会分叉。

| 路径 | 说明 | 可以删吗 |
|---|---|---|
| `state/quota.json` | 当日网络动作计数 | 删了等于当天配额清零，不建议 |
| `state/cooldown.json` | 风控冷却 | 只在人工完成验证后用 `reset --confirm` |
| `state/plan.lock` | 计划锁 | 有进程卡死时可删 |
| `audit/audit.jsonl` | 动作审计 | 可归档 |
| `cache/cache.sqlite3` | 响应缓存（7 天） | 可删，删了下次重新抓 |
| `host/bridge.json` | 宿主端点与令牌 | 由宿主自动重建 |
| `host/logs/host.log` | 宿主日志 | 可轮转 |
| `installations/<版本>/` | 部署树 | 旧版本可删 |

## 3. 从零安装（部署树方式）

```powershell
# 1) 解包/安装到新版本目录（<版本> 换成实际版本号，例如 0.3.18）
$ver = '<版本>'
$root = "$env:LOCALAPPDATA\scholar-search\installations\$ver"
python -m venv "$root\venv"          # 或复制现有 venv 再替换 site-packages
& "$root\venv\Scripts\python.exe" -m pip install .\dist\wensu-$ver-py3-none-any.whl

# 2) 导出资源 + 注册原生宿主（写清单 + HKCU 注册 + 低完整性标签）
#    资源与安装包一致时这一步只做宿主部分，不一致才替换；不需要 --force
& "$root\venv\Scripts\python.exe" -m scholar_search.cli setup --target "$root\browser" --browser none

# 3) 装扩展：edge://extensions → 开发者模式 → 加载解压缩 → $root\browser\extension
# 4) 验证
$env:SCHOLAR_SEARCH_HOME = "$env:LOCALAPPDATA\scholar-search"
& "$root\venv\Scripts\python.exe" -m scholar_search.cli status
```

不想用 `pip`，也可以直接用 wheel 解压覆盖 `site-packages`：

```powershell
Expand-Archive .\dist\wensu-$ver-py3-none-any.whl -DestinationPath .\wheel
Copy-Item .\wheel\scholar_search "$root\venv\Lib\site-packages\" -Recurse -Force
Copy-Item .\wheel\wensu-$ver.dist-info "$root\venv\Lib\site-packages\" -Recurse -Force
```

## 4. 升级

```powershell
# 1) 用当前版本目录复制出新目录（现在只保留一个安装目录，没有"上一版"可复制）
$old = '<当前版本>'    # 例如 0.3.18
$new = '<新版本>'      # 例如 0.3.19
Copy-Item "$env:LOCALAPPDATA\scholar-search\installations\$old" `
          "$env:LOCALAPPDATA\scholar-search\installations\$new" -Recurse

# 2) 在新目录里换包
$target = "$env:LOCALAPPDATA\scholar-search\installations\$new"
Expand-Archive .\dist\wensu-$new-py3-none-any.whl -DestinationPath .\wheel-new
Remove-Item "$target\venv\Lib\site-packages\scholar_search*","$target\venv\Lib\site-packages\wensu-*" -Recurse -Force
Copy-Item .\wheel-new\scholar_search* "$target\venv\Lib\site-packages\" -Recurse -Force

# 3) 刷新资源并重注册宿主：内容与安装包一致时只做宿主部分，不一致才替换（无需 --force）
& "$target\venv\Scripts\python.exe" -m scholar_search.cli setup --target "$target\browser" --browser none

# 4) 更新 MCP 客户端里的解释器路径（Codex / DSH bundle / Claude Desktop …）
#    扩展一般不用重装：只有 extension/ 的 JS 或 manifest.json 变了才重载

# 5) 重启客户端（stdio server 是子进程，导过的模块不会热更新）
```

升级后确认三件事：

1. `status` 里 `bridge_ready: true`；
2. 版本号两处都对：`python -m scholar_search.cli --version` 与 `status.version`；扩展副本看
   `status.browser_profile.extension_version`（与本版本不同时会带
   `extension_version_mismatch: true`）——不一致就跑一次 `wensu setup`，再到 `edge://extensions`
   点「重新加载」；
3. 跑一次真实检索（知网 3 个配额 / WoS 8 个）。

## 5. 回滚

部署树模式最简单：

1. 把 MCP 客户端的解释器路径改回旧版本目录；
2. 重跑旧目录的 `install.ps1`（让宿主的 `python-path.txt` 与注册表回到旧版）；
3. 重启客户端；
4. 扩展不用动。

注意：**不要**让两个版本同时对着同一个 `SCHOLAR_SEARCH_HOME` 长期跑，配额会打架。

## 6. 常用命令

```powershell
wensu status                 # 渠道、剩余配额、冷却、桥接是否就绪、扩展副本版本
wensu setup                  # 刷新资源副本 + 重写宿主清单（内容一致的部分会跳过）
wensu assets --target .\b    # 只导出资源（同名目录内容一致时跳过，不同则替换）
wensu reset --confirm        # 人工完成验证后清除冷却（显式、不可撤销）
wensu serve --transport stdio
wensu serve --transport http --host 127.0.0.1 --port 8765
wensu --version
```

### 部署后的一次性真机自检

`scripts/accept-live.py` 是给维护者的冒烟脚本：绕开 MCP 客户端，直接对着活的桥跑
一次检索（可选再取一条详情 + 导出首行），能同时验证渠道、解析和浏览器链路。

```powershell
$env:SCHOLAR_SEARCH_HOME = "$env:LOCALAPPDATA\scholar-search"
& "<安装目录>\venv\Scripts\python.exe" scripts\accept-live.py "IPMC" --limit 3
& "<安装目录>\venv\Scripts\python.exe" scripts\accept-live.py "IPMC" --limit 3 --detail
```

它花真配额：一次检索 3 个网络动作，加详情 1 个。跑之前先 `status` 看余量。

## 7. 排障

按现象查，先看 `audit/audit.jsonl` 最后几条，再看浏览器状态。

| 现象 | 先查 | 处理 |
|---|---|---|
| `bridge_ready: false` | 宿主进程是否在跑（`Get-Process scholar-host`）、`host/bridge.json` 是否新鲜 | 重启浏览器；仍不行重跑 `install.ps1` |
| 动作报 `content_not_ready` | **浏览器窗口标题是不是"隐私错误"** | 多半是代理换证，见下节 |
| `sleep` / `type` 报 `bridge.timeout`，`duration_ms` 贴着超时值 | 窗口是否在前台、是否只有一个可见窗口 | 把 CNKI 窗口切前台；0.3.15 起暂停已带 2s 余量，仍超时说明节流更狠 |
| `goto` 15s 超时 | 是否长期复用同一个 CNKI 标签页 | 关掉所有 CNKI 标签页或重启浏览器 |
| `blocked` + `cooldown_until` | `audit.jsonl` 里的 `signal` | 人工在浏览器完成验证，再 `reset --confirm`；**不要**重试 |
| 新浏览器环境第一次检索就 `blocked`（`verify_redirect`） | 新 profile 无 Cookie/历史，站点要求人工验证 | 属预期；按上一条处理后重试一次，见 [浏览器环境](browser-setup.md#61-全新环境第一次访问几乎一定会遇到安全验证) |
| `policy.params` | 参数是否越界（page>3、limit>50、未知动词） | 按提示改参数 |
| `ParseError` | 页面结构是否变了 | 见 [知网改版应对](cnki-maintenance.md) |
| 配额用尽 | `quota.json` 的 `day` 字段 | 等次日自动重置；不要改计数绕过 |

### 代理导致证书错误（很常见）

现象：`goto` 成功但页面是"隐私错误"，后续动作全部 `content_not_ready`；
报错是 `NET::ERR_CERT_COMMON_NAME_INVALID`。

原因：系统代理（Clash、v2ray 等）对 `kns.cnki.net` 做了 TLS 中间人，证书名对不上。

处理，二选一：

- 在代理软件里加规则 `DOMAIN-SUFFIX,cnki.net → DIRECT`（推荐，持久）；
- 或者把 `*.cnki.net;cnki.net` 加进
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings` 的 `ProxyOverride`
  （改完用 `InternetSetOption(NULL, 39/37, ...)` 广播，或重启浏览器）。

判断技巧：PowerShell 的 `Invoke-WebRequest` 不走 WinINET 注册表代理，它能通不代表浏览器能通。

### 浏览器定时器节流

窗口不在前台时浏览器把定时器按整秒分桶，暂停最多晚到近 1 秒；隐藏超过 5 分钟还有更狠的
节流。所以：**跑检索时把 CNKI 窗口切到前台，只留一个可见窗口、一个 CNKI 标签页**。
`settle()` 的 2s 余量只覆盖前一种情况。
