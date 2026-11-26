# wensu 0.14.29 安装与修复复验

**结论：0.14.29 已安装，但不能判定整版验收通过。F01、F11、F12 的安装版定向测试通过；主读取路径的判墙在合成回放中通过。真实运行的 worker 构建信息没有取得，能力门在能力未知时放行；另复现 F05、F07、F10 的残留分支。真实站点判墙验收未完成。**

日期：2026-11-26，北京时间。仓库基线 `b87c464`。本轮只更新本机安装，新增测试脚本和本报告，没有修改业务实现，没有发布或提交。

## 安装与版本证据

- 官方 PyPI 与 npm 均可取得 `0.14.29`，未把 npm 工作流的 failure 直接当成包发布失败。交接所述“同名版本重复发布导致 CI 失败”的原因未另行审查 CI；本轮验证的是 registry 实际可取得包。
- 官方 wheel 在 PyPI 元数据中的 SHA-256 为 `7fa956dafaf5b78403b8bb503b9d194a8acb37d21bd06ac0b17c7727e0834e46`。安装由包管理器从官方索引完成；未把本地重建 wheel 的哈希冒充这个发行包哈希。
- 新建 `%LOCALAPPDATA%\scholar-search\installations\0.14.29\venv` 安装官方发布包；全局 CLI 与 DSH bundle 均更新为 0.14.29。
- Codex 配置已指向新版 venv；native host 注册指向该版本目录。原扩展加载路径下文件更新为 0.14.29；用户确认已重新加载。
- 为解除全局 CLI 文件占用，只停止了先打印并复核命令行的全局 serve PID `9700`、`28232`。没有按进程名停止浏览器，也没有批量停止其他版本的 MCP。
- 私有补丁在新版 venv 和全局安装分别恢复，两次原有自检均通过；补丁代码未复制入公开仓库。原浏览器 profile、配额和冷却保留。
- 配置及扩展备份位于新版安装目录的 `upgrade-backups\20261126-175812`。移除了 pnpm 此次自动增加的 release-age 例外，没有保留新增的策略放宽。
- 除私有覆盖点 `core/page_nav.py` 外，发布安装包与仓库的 **52 个 Python 文件**在归一化换行后完全一致。
- 独立正式 MCP 客户端握手返回 `wensu 0.14.29`。本聊天原驻留连接的版本没有被拿来冒充新版测试。

来源：[PyPI 0.14.29](https://pypi.org/project/wensu/0.14.29/)、[npm 0.14.29](https://www.npmjs.com/package/@hui-xu-ai/dsh-wensu/v/0.14.29)。

## 1 运行中的 worker 构建信息

**结果：未通过。不能确认实际 worker 文件名，也不能据此认定用户没有重载。**

用户确认重载后，通过新安装环境启动正式 MCP 服务，完整 status 回包为：

```json
{
  "version": "0.14.29",
  "bridge_ready": true,
  "browser_profile": {
    "extension_version": "0.14.29",
    "extension_version_mismatch": false,
    "bridge_build": {"host_version": "0.14.29"}
  }
}
```

两点与交接的验收口径不同：字段实际在 `status.browser_profile.bridge_build`，不是顶层；其中没有 worker、worker version、capabilities 或 channel_capabilities。顶层 `channel_capabilities` 是渠道题录能力字典，不能代替 worker 的动作能力列表。

后续尝试初始化协议握手超时，`adapter.info()` 仍只有 host_version。日志确认新的 0.14.29 native host 已在用户重载时启动；不能把“host 已启动”和“扩展协议握手成功”当作同一个事实。此次未确认真实握手超时的完整根因。

代码中可确定的冷启动缺口：`BridgeHost.build` 初始为空，只有 `_handshake()` 才填充；`build_info()` 直接返回当前字典；`cmd=info` 不触发握手。因此即使 worker 本身正常，首次 status 和首次能力预检也可能只得到空构建信息。

定位：`src/scholar_search/adapters/bridge/host.py:74`、`:114`、`:156`；`native-host/main.py` 的 `cmd=info` 分支；`bootstrap.py:169`。

建议：构建信息查询先完成有界握手，明确区分“尚未握手”“旧 worker 不支持”“握手失败”。status 应将运行版本未知标记为未知，不能仅凭磁盘 manifest 相等表示运行版本一致。

## 2 page 计划的能力门

**结果：真实运行未通过，零额度拒绝条件未成立。**

测试使用 `page:mdpi` 的计划，包含 goto 和 wait_for。先只调用能力预检，没有执行计划：真实 info 只有 host_version，`_ensure_capabilities` 未拒绝。原因是 `capabilities` 缺失或为空时直接 return。

随后用于初始化握手的失效快照续块令牌请求超时，构建信息仍未补齐。测试脚本本应在此停止，但旧版脚本漏了这个保护，随后调用计划执行，最终观察到：

```json
{
  "cold_gate_rejected": false,
  "warm_build": {"host_version": "0.14.29"},
  "warm_gate_code": "bridge.error: timed out",
  "actions_executed": 1,
  "quota_delta": 1
}
```

一条 goto 进入执行，17.013 秒后返回 bridge 超时。不能认定它成功到达了站点，也不能把它描述为“零网络、零额度的拒绝测试”。已经停止现场动作，没有重试。测试脚本已增加强制保护：即使能力门放行，执行包装器也拒绝发送任何动作；未用修改后的脚本重跑现场来掩盖原始结果。

本轮真实额度 **272 → 271**；读取真实状态确认没有冷却。负数配额测试使用的是另一份临时文件，与这次真实扣费无关。

定位：`core/service.py:1531` 的空能力回退；`_run` 在 planner 之前调用能力门的顺序本身正确，但缺少可靠的前置握手使它失效。

建议：新版 host 的能力未知时明确拒绝或报告初始化未完成。旧 worker 兼容可以单独提供受限行为，不能把“查询失败”和“旧 worker”统一解释为无须校验。新增测试应从刚创建、尚未握手的 host 开始，走 info → service → planner，而不只给 stub 预置完整能力列表。

## 3 持续验证墙与暂态标题

**结果：主读取路径的安装版合成回放通过；真实 Cloudflare 验收未完成。**

| 输入 | 安装版返回 |
|---|---|
| 导航标题像中间页，快照仍是验证墙 | `blocked/challenge`，`full_text=false`，`mhtml_path=null` |
| 导航标题像中间页，快照已是正常正文 | `ok`，`full_text=true`，保存正文 |

使用的是安装版加原有私有补丁的形态，两条合成导航的报价均为 2。测试没有访问或尝试通过任何真实验证码。

真实协议握手未验收成功后，没有继续尝试文章导航，不能把合成回放当成真实 Cloudflare 中间页已通过。没有以反复导航来制造验证墙。

### 全文视图仍会隐藏快照识别出的墙

另一个安装版合成用例：初始落地页只有付费墙；全文跟随的 goto 返回普通标题，但随后快照识别出真正的验证墙。最终仍返回初始 `no_html/paywall`，并保留初始文件路径，而不是 blocked/null。

原因：`_follow_fulltext` 把这种情况放在 `_FollowResult.saved`，调用方只检查 `follow.blocked`，所以只有抛出的 RiskBlocked 被修复，快照返回的 blocked 字典仍被折叠为“没有改善”。这意味着“判墙修复通过”必须限定在主读取路径。

## 4 负数配额与空 HTTP 令牌

**F11：通过。** 在隔离临时目录写入当天 `used=-20`：

```json
{"remaining":null,"state_error":"corrupt","network_slot_refused":true,"state_unchanged":true}
```

不是 320，也没有把文件改成新额度。`wait_turn()` 拒绝分配动作。

**F12：通过。** 在另一临时家创建空 http-token，实际启动安装版 HTTP CLI，进程退出码为 1，错误包含 unusable token；空文件保持不变，没有启动为可服务的 HTTP 传输。这不是只测试 load_token 函数。

上述操作没有更改用户真实的 quota.json 或 http-token。

## 5 图片路径边界

**F01：本轮要求的定向用例通过。**

把引用父目录、绝对路径以及一个合法同目录图片的合成 HTML 交给安装版 `page2md.convert`：

```json
{
  "images_missing": 2,
  "images_copied": 1,
  "outside_bytes_copied": false,
  "inside_image_copied": true
}
```

这是整个 HTML 转换入口的测试，不只是路径辅助函数。没有尝试读取用户的真实私有文件。未把本轮两种路径样本扩大解释为所有文件系统边界情况已穷尽。

## 补充发现的残留分支

### F05 页面没有 DOI 元数据时仍可能串文

请求 Wiley DOI `10.1002/pen.23634`，快照 URL 却属于 ACS 的另一篇文章。

| 快照元数据 | 安装版结果 |
|---|---|
| 明确声明另一 DOI | 正确返回 `no_page/capture_mismatch`，无文件 |
| 没有 citation_doi | 仍返回 `ok`、`full_text=true`，captured_url 是 ACS 页面 |

修复仅拒绝矛盾 DOI；缺少元数据时仍未落实捕获 URL、出版社归属和导航身份校验。

定位：`core/service.py:1232`，条件要求 requested DOI 和 declared DOI 同时非空。建议先校验稳定 tab/navigation 身份与捕获 URL 的可接受归属，再把 citation_doi 当成额外证据。

### F07 私有补丁的失败费用仍少报

安装版原有私有补丁形态：首次访问两次导航，全文跟随又执行两次，最后一条触发合成 403。

结果已正确传播 `blocked/http_403` 和冷却，但 `quota_charged=3`、临时策略实际使用 4。定位 `core/service.py:916`：异常分支仍硬编码 `charged=1`。首读异常出口 `:1111` 也仍有常量报价，应一并检查。

建议由本次请求实际动作账本统计异常费用，不把“导航计划”假定为只有一条 goto。公开发行物可测试可替换导航契约，不需复制私有实现进公开仓库。

### F10 本地图像的同名冲突仍存在

两个合法子目录分别有不同内容的 figure.png。转换后两个 Markdown 引用都指向 assets/figure.png，第二份覆盖第一份；回报 copied=2、missing=0，没有说明第一张图已被替换。

内联 MHTML 的内容哈希命名和同一输入更新后重拷贝确实改善了原问题，但本地图片分支 `page2md.py:1070` 仍使用 candidate.name。建议本地资源也采用稳定且唯一的映射。

## 发布检查与证据

`scripts/release-check.py` 本轮十门全部通过：versions、tool-schema、changelog、tests、lint、format、types、plans、assets、artifacts。格式门覆盖 141 个文件，mypy 检查 53 个源文件，wheel 为 75 个文件并包含两个渠道。没有用绿灯代替上述现场和边界验收。

复现脚本：`work/verify/2026-11-26-codex-01429/verify_installed.py`。其 offline 模式只用安装版、合成页面和临时状态；capability 模式涉及真实 host，原始那次未通过并消耗一个真实配额，后续已加防护且未重跑。

原始结构化结果在私有运行目录 `%LOCALAPPDATA%\scholar-search\verification\2026-11-26-codex-0.14.29\`：initial-status.json、offline-checks.json、capability-checks.json。文件不含桥接 token；私有补丁源码和页面全文未复制进公开仓库。

## 下一批改进及验收顺序

1. 先修运行握手与冷启动能力状态。一次新的 host 启动后，首次 status 就必须给出实际 worker 或明确的初始化错误；缺失能力不能放行。不要把问题归结为让用户反复重载。
2. 合并全文跟随的所有 blocked 表达，并消除失败报价常量；分别覆盖抛异常、标题门、快照返回 blocked 和多导航计划。
3. 完成缺少 DOI 元数据时的捕获身份校验，以及本地图像唯一命名。
4. 上述回归通过后，再验证一篇真实文章及一个自然出现的中间页；真实 blocked 后立即停止，不自动重试或清理风控状态。

本报告不提出修改私有补丁的实现，也没有主动修复产品工程。当前建议状态是“部分修复通过，整版待验收”，不是“全部修复完成”。
