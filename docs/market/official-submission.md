# 上架官方市场（awesome-dsh-plugin）：我们缺什么、怎么交

日期：2026-11-27。目标版本 0.15.0。规则来源：官方
[`contributing.md`](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/blob/main/contributing.md)
（2026-11 版）。**唯一投稿渠道**是向该仓库提 PR，加一个 YAML；市场（`dshmarket`）每次打开实时读
`https://awesome-dsh-plugin.com/plugins.json`，没有"上传安装包"入口。

## 一、我们已经满足的

| 条件 | 我们的状态 |
|---|---|
| 公开 GitHub 仓库 | `github.com/hui-xu-ai/wensu` |
| `package.json` 声明 `dsh.bundle.patch` | `packages/dsh-wensu/package.json` ✅，`cordis.patch.yml` 在同目录 |
| monorepo 子包可独立安装 | 已发 npm `@hui-xu-ai/dsh-wensu@0.15.0` |
| 仓库创建满 1 天 | ✅（老仓库） |
| 真实可用代码 | ✅（不是占位、不是纯 README） |
| `repository` 指回本仓库 | ✅ 会与 npm 包自动关联（条目里**不要**写 `npm:`，会被校验拒绝） |
| MIT LICENSE | ✅ |

## 二、还缺的（只有你能做）

1. **给仓库加 `dsh-plugin` topic**（GitHub 仓库页 → About 齿轮 → Topics）。CI 会看。
2. **fork 并提 PR**（需要 GitHub 账号；我这边没有推送权限）。
3. 可选但推荐：在 `packages/dsh-wensu/` 放一张 180×180 的 PNG 图标，条目里用
   `icon: https://raw.githubusercontent.com/hui-xu-ai/wensu/main/packages/dsh-wensu/assets/icon-180.png`
   ——**只收 GitHub 托管的位图**，SVG 会被拒；不写则回退到作者头像。

## 三、要交的那个文件（可直接复制）

路径：`data/plugins/hui-xu-ai__wensu--packages-dsh-wensu.yml`

```yaml
url: https://github.com/hui-xu-ai/wensu/tree/main/packages/dsh-wensu
name: hui-xu-ai/wensu#dsh-wensu
category: tools
description:
  en: Mounts the wensu MCP server so a session can search CNKI and Web of Science and read a paper's full text from the browser you are already signed in to. Read-only; no PDF downloads.
  zh: 挂载文溯 MCP 服务：在已登录的浏览器里检索知网与 Web of Science 题录，并读取论文全文。只读，不下载 PDF。
```

- 文件名必须与 `url` 推出的 slug 一致：`owner__repo--packages-dsh-wensu.yml`（子目录用 `-` 连接）。
- `name` 用 `owner/repo#subname`，`subname` 取子目录最后一段（`dsh-wensu`）。
- `description.en` 是**唯一必填**字段：单行、以句号结尾、只说功能。含 `: ` 时必须加引号（上面这条不含）。
- 不写注释；一个 PR 最多 3 条（我们只需 1 条）。

## 四、提交步骤

```powershell
# 1) fork（网页或 gh）
gh repo fork awesome-dsh-plugin/awesome-dsh-plugin --clone
cd awesome-dsh-plugin
git switch -c add-wensu

# 2) 只加那一个文件
#    把上面 YAML 存成 data/plugins/hui-xu-ai__wensu--packages-dsh-wensu.yml

# 3) 本地自查（跑的就是 CI 那套校验，文件名或 url 写错会当场报错）
npm ci
node scripts/generate-readme.mjs

# 4) 提 PR
git add data/plugins/hui-xu-ai__wensu--packages-dsh-wensu.yml
git commit -m "Add hui-xu-ai/wensu#dsh-wensu"
git push -u origin add-wensu
gh pr create --title "Add hui-xu-ai/wensu#dsh-wensu" --body "wensu bundle 0.15.0"
```

**不要**手工编辑两个 README——它们由 `data/plugins/*.yml` 生成，合并后自动重建。

## 五、最可能被打回的地方（提前想清楚）

1. **"纯聚合包"规则（gate #7）**：官方明确写"只装一组别的插件、自己不带行为的聚合包不单独收录"。
   我们的 bundle 内容是一份 `cordis.patch.yml`（把 `dsh-mcp-client` 配上 wensu 的 stdio 命令与参数）
   + README。按规则里"**composes configuration**（合成配置）的聚合包算插件"这一条，我们应该属于插件；
   但这是**维护者的判断**，不是 CI 能过的。PR 描述里应直接说明这一点，而不是等对方问。
2. **描述必须与代码相符**：不要写"12,000 篇"、"六大数据源"这类数字；上面那条描述只说了实际有的
   两个渠道（CNKI / Web of Science）与只读抓取。
3. **仓库要活跃**：长期停更会被定期扫描标记并移除。
4. **镜像不等于上游**：`registry.npmmirror.com` 可能滞后；条目本身不依赖镜像，但你在国内验证安装时
   要显式传官方 registry（`plugin_manager` 的 `registry` 参数）。

## 六、与"我们自己的索引源"的关系

两条渠道互不影响：

| 渠道 | 地址 | 谁维护 |
|---|---|---|
| 官方市场 | `awesome-dsh-plugin.com/plugins.json` | 上游仓库 PR，约 1 天生效 |
| 我们自己的索引源 | `https://hui-xu-ai.github.io/wensu/market/index.json` | 我们自己，推送即生效 |

**本地索引已经补齐**（`docs/market/index.json`：129 个版本，头部 0.15.0）。它此前停在 0.14.18，
落后 50 个版本——这次用 npm registry 的 `time` 字段回填，`publishTimestamp` 全是 10 位秒级 epoch。
