# 发布

仓库远程是 `origin` → `github.com/hui-xu-ai/wensu`。

> **四个发行物共用一个版本号**（ADR 0013）：Python 包、浏览器扩展、native host、DSH bundle。
> 版本号写五处，由 `scripts/check-versions.py` 校验。

## 0. 一条命令

```powershell
python scripts/release-check.py
```

七项全绿才往下走。它检查什么、每项为什么存在，写在脚本开头的 docstring 里：
版本一致、CHANGELOG 有条目、测试、lint、类型、两层计划校验、wheel 装得下两个渠道。

慢的话可以 `--skip-slow` 跳过测试和构建，但**打 tag 之前要跑完整的**。

## 1. 然后三步

```powershell
git add -A
git commit -m "chore: release 0.12.10"
git tag -a v0.12.10 -m "wensu 0.12.10"
git push origin main
git push origin v0.12.10
```

推送后 CI 自动完成：构建 wheel + sdist → 校验 tag 与 `__version__` 一致（不一致直接失败）→
建 GitHub Release → 发布 PyPI。约一分钟。

**改文档也必须发版才能更新 PyPI 页面**：`pyproject.toml` 的 `description` 是页头、
`README.md` 是正文，两者都在构建时打进 wheel，已发布版本不能覆盖，只能发新版本。

## 2. bundle 与插件市场

bundle 走另一条流水线，tag 前缀是 **`npm-v`**，但**这个 tag 只是版本记录，不负责发布**：
本仓库没有配 `NPM_TOKEN`，`publish-npm.yml` 被 tag 触发后必然失败在
`Publish with OIDC trusted publisher`。**发布由本机 `pnpm publish` 完成**（下一段命令），
失败的 run 不影响任何东西。bundle **不产生 GitHub Release** —— Release 只跟 Python 包
（`v*` tag → `release.yml` → GitHub Release + PyPI）。

> npm token 失效属于**前置条件**问题，不是发布步骤：`pnpm whoami` 报 401 时按 §5
> 「`whoami` 报 401 时」那三步处理，与本节的发布命令无关。

```powershell
git tag -a npm-v0.12.10 -m "dsh-wensu bundle 0.12.10"
git push origin npm-v0.12.10
```

本地直接发也可以（CI 缺 `NPM_TOKEN` 时用这条）：

```powershell
$node = 'D:\DSH\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
$pnpm = 'D:\DSH\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\pnpm\bin\pnpm.mjs'
Set-Location packages\dsh-wensu
& $node $pnpm whoami --registry https://registry.npmjs.org/   # 应先确认身份
& $node $pnpm publish --access public --no-git-checks --registry=https://registry.npmjs.org/
```

发出去之后**再做两件事**：

1. `docs/market/index.json` 的 `versions` 数组**头部**插入新版本（`publishTimestamp` 用
   registry 返回的秒级 epoch）。**顺序不能反**——先写索引会让市场指向一个装不下来的版本。
2. 提交并推送。市场从 GitHub raw 拉取，约一分钟生效。

### 发出去 ≠ 立刻能装：两处延迟都要会绕

- **npm 自己也有 CDN 缓存**（2026-11-18 实测）：`pnpm publish` 打印 `✅ Published` 之后，
  `GET /<包>/0.12.57` 与 `dist-tags` 仍可能返回 404 / 旧值约 1–5 分钟。判断"到底发没发成功"
  的硬证据有两条：① 再发一次会得到 `403 … cannot publish over the previously published versions`；
  ② 稍后 `GET` 变 200。别因为前 60 秒 404 就重复发布。
- **DSH 的插件安装走 `registry.npmmirror.com` 兜底**（`plugin_manager` 返回里的
  `registries: [null, "https://registry.npmmirror.com/"]`）。镜像同步新版本要几分钟到更久，
  期间 `plugin_manager install_bundle` 会报 `ERR_PNPM_NO_MATCHING_VERSION`（"latest is 0.12.x"）。
  两条绕法：`install_bundle` 显式传 `registry=https://registry.npmjs.org/`；或干脆在 profile 里
  直连安装：

  ```powershell
  cd D:\DSH\.dsh\profiles\desktop
  & $node $pnpm add "@hui-xu-ai/dsh-wensu@<新版本>" --save-exact --registry=https://registry.npmjs.org/
  ```

  装完 `plugin_manager list_bundles` 里该 bundle 应显示新版本、`enabled: true`、
  `rows: [mcp-scholar-search]`、**没有 `error`**；`remove_bundle` 会把它置为 `enabled: false`，
  需要 `set_bundle enabled=true` 再启用一次。

## 3. 发布前检查的细节

`release-check.py` 之外，这几条仍需人看：

- `.gitignore` 覆盖 `dist/`、`.venv/`、`*.log`、`native-host/` 下的生成物
  （`scholar-host.exe`、`python-path.txt`、`com.scholar.search.json`）；
- 没有真实 Cookie、账号、会话参数、个人检索记录混进 `tests/fixtures/`；
- `README.md` 里的版本号与 `pyproject.toml` 一致（`check-versions.py` 会拦）。

## 4. CI 与发布流水线

| 工作流 | 触发 | 做什么 |
|---|---|---|
| `.github/workflows/ci.yml` | push 到 `main`、所有 PR | Ubuntu + Windows × Python 3.11/3.12：`ruff check .`、**版本一致**、`mypy src`、`pytest -m "not e2e"` |
| `.github/workflows/release.yml` | 推送 `v*` tag | 构建 wheel + sdist，校验 tag 与 `__version__` 一致，创建 GitHub Release 并附产物，发布 PyPI |
| `.github/workflows/publish-npm.yml` | 推送 `npm-v*` tag | 校验 tag 与 bundle 版本一致，发布 npm |

`release.yml` 的版本校验会拦下「tag 打了但版本号没改」。

### tag 与 main 一起推时的时序坑

首次建库时实测：先 `git push -u origin main`、紧接着 `git push origin --tags`，25 个 tag 全部
推上去了，但**一个 release 工作流都没触发**。原因是 GitHub 处理 tag 事件时，`release.yml` 在
默认分支上还没生效（工作流文件刚随 main 推上去几秒）。

处理：单独重推需要发版的那个 tag——

```powershell
git push origin :refs/tags/v0.3.18    # 删远端 tag
git push origin v0.3.18               # 重新推，触发 release
```

不要把历史 tag 挨个重推，那会一次生成几十个 release。

### 补 tag 但不想重新发版

```powershell
gh api -X PUT repos/<owner>/<repo>/actions/workflows/release.yml/disable
git push origin v0.3.17
gh api -X PUT repos/<owner>/<repo>/actions/workflows/release.yml/enable
```

**tag 不占存储**，只删 release 就够了；每个 release 的产物才是空间大头。

## 5. 分支保护与合并

建议在 GitHub 上对 `main` 开启：要求 PR、要求 CI 通过、禁止 force push。

## 6. 发行渠道说明

推送 `v*` tag 会触发 `.github/workflows/release.yml`，它做四件事：构建 → 校验 tag 与
`__version__` 一致 → 建 GitHub Release → 发布 PyPI。

实测（2026-11-09，`v0.12.10`）：tag 推上去约一分钟，Release 页面出现产物，PyPI 上
`info.version` 同步更新，`pip install -U wensu` 即可装到。

前置条件（一次性，已完成）：PyPI 上项目 `wensu` 的 trusted publisher 指向本仓库的
`release.yml`，无需 API token。换仓库或改工作流文件名要同步改，否则报 `invalid-publisher`。

### npm 的两条认证路径

`.github/workflows/publish-npm.yml` 要么用仓库 secret `NPM_TOKEN`，要么用 npm 的 Trusted
Publisher（OIDC）。**没有 token 时会自动尝试 OIDC**，两条都没配就失败在
`Publish with OIDC trusted publisher` 那一步。

配置 `NPM_TOKEN`：<https://www.npmjs.com/settings/hui-xu-ai/tokens> 生成 **Classic →
Automation**（Granular 需要同时勾 Packages 与 Organizations，容易漏）。

**必须放 Repository secrets。** 该工作流没有 `environment:` 声明，environment 层的 secret
读不到，表现和「根本没配」完全一样——这一条踩过。

**本地发布的坑**：凭据走 `~/.npmrc` 的 `_authToken`，**不是** `NODE_AUTH_TOKEN` 环境变量。
`pnpm whoami` 能返回用户名再去 publish。

**改 token 最快的办法（推荐）**：`notepad $env:USERPROFILE\.npmrc`，把
`//registry.npmjs.org/:_authToken=` 那一行整行替换成新 token（等号后直接跟 `npm_...`，
不要引号、不要空格），保存即可 —— 与 `npm config set` 完全等价，但不会被引号/转义坑到，
也不进命令历史。改完先看 mtime 确认真的存了。

**`whoami` 报 401 时，按这三步定位，不要重试原命令**（2026-11-18 实测浪费了三轮）：

1. **换了吗？** 看 `~/.npmrc` 的修改时间 —— 如果还是几天前，那就是**根本没换过 token**，
   后面的判断都不用做：

   ```powershell
   (Get-Item $env:USERPROFILE\.npmrc).LastWriteTime
   ```

2. **token 本身活不活？** 绕过 pnpm，直接问 registry（这一步能区分「token 死了」和
   「pnpm 没读到」）：

   ```powershell
   $t = (Select-String -Path $env:USERPROFILE\.npmrc -Pattern '^//registry\.npmjs\.org/:_authToken=(.+)$').Matches[0].Groups[1].Value.Trim()
   Invoke-RestMethod https://registry.npmjs.org/-/whoami -Headers @{Authorization="Bearer $t"}
   ```

   401 ⇒ 去 <https://www.npmjs.com/settings/hui-xu-ai/tokens> 重新生成 **Classic → Automation**
   并覆盖同一行；200 ⇒ token 没问题，进第 3 步。

3. **pnpm 读的是不是同一个文件？** `pnpm config get //registry.npmjs.org/:_authToken`
   （会回显，注意别贴到公开场合）应当与第 2 步取到的值一致；`npm config get userconfig`
   应指向同一个 `~/.npmrc`。不一致就先查项目级/`prefix` 级 `.npmrc` 与环境变量。

判据只有一条：**「服务端说你是谁」才算数**，`whoami` 报错本身不说明原因。

### 市场页面的介绍文字

`docs/market/index.json` 的 `title` / `description` / `metadata.labels` / `metadata.keywords`
就是市场展示的内容。**改描述不需要发版**，推送即生效；只有 `versions` 数组要等 npm 发布成功。

## 7. 不要提交的东西

- `HANDOFF.md`（本机路径、个人排障笔记；已加入 `.gitignore`）
- `dist/`、`.venv/`、`browser/`（资源构建产物）
- `native-host/python-path.txt`、`com.scholar.search.json`、`scholar-host.exe`
- 任何 `%LOCALAPPDATA%\scholar-search` 下的运行期文件
