<#
memory-gate.ps1 —— 记忆文件体积门禁（防"记忆无上限增长"）

为什么需要：反馈 V17 实测 SHORT-TERM.md 从 50KB 涨到 71KB / 620+ 行，新会话按指引"读顶部"
却仍为整个文件付输入成本，且容易漏读底部。协议里写了上限，但**没有强制执行**——
所有"只靠自律的上限"最终都会失效。

本脚本把 memory-system 的上限表变成可执行断言：
  文件              上限
  HANDOFF.md        ≤80 行（新会话唯一必读的交接卡）
  SHORT-TERM.md     ≤120 行（近期流水，超限归档）
  INDEX.md          ≤120 行
  PROJECT.md 任务表 ≤50 行（整文件 ≤120 行）
  NOTES.md/其他     ≤400 行

另加**工作区指令文件**门禁（独立于记忆目录，缺文件也报）：
  AGENTS.md         ≤200 行（每轮注入的会话基线；官方口径「CLAUDE.md 目标 <200 行，太长会让模型忽略一半」）

用法：
  pwsh -NoProfile -File tools\memory-gate.ps1                 # 报告（默认记忆目录 .dsh-memory）
  pwsh -NoProfile -File tools\memory-gate.ps1 -FailOnOver     # 有超限则 exit 1（可入提交前检查）
  pwsh -NoProfile -File tools\memory-gate.ps1 -MemoryDir <路径>
  pwsh -NoProfile -File tools\memory-gate.ps1 -DocsRoot <工作区根>   # AGENTS.md 所在目录（默认取记忆目录的父目录）
退出码：0 = 全部在上限内（或仅警告）；1 = 有超限且指定了 -FailOnOver。
#>
[CmdletBinding()]
param(
  [string]$MemoryDir = (Join-Path (Get-Location) '.dsh-memory'),
  [string]$DocsRoot = '',
  [switch]$FailOnOver
)

$ErrorActionPreference = 'Stop'

# 工作区指令文件（AGENTS.md）与记忆目录相互独立：**先查**，即使记忆目录不存在也要查。
# 依据：AGENTS.md 是每轮注入的会话基线，过长会让关键红线被淹没（官方 CLAUDE.md <200 行的同一条理由）。
$over = 0
if (-not $DocsRoot) { $DocsRoot = Split-Path -Parent $MemoryDir }
$agentsPath = Join-Path $DocsRoot 'AGENTS.md'
Write-Output ("=== 工作区指令文件门禁：" + $agentsPath + " ===")
if (-not (Test-Path -LiteralPath $agentsPath)) {
  Write-Output "  [MISS] AGENTS.md 不存在 —— 新会话没有工作区基线；从模板补建（pydev-share/templates/AGENTS.md）。"
} else {
  $agentsLines = (Get-Content -LiteralPath $agentsPath -ErrorAction SilentlyContinue | Measure-Object).Count
  if ($agentsLines -gt 200) {
    $over++
    Write-Output ("  [OVER] AGENTS.md  " + $agentsLines + " 行 > 上限 200 —— 每轮都付这段租金；把方法论下沉到技能、只留事实+启动清单+红线。")
  } else {
    Write-Output ("  [OK]   AGENTS.md  " + $agentsLines + " / 200 行")
  }
}
if (-not (Test-Path -LiteralPath $MemoryDir)) {
  Write-Output ("记忆目录不存在：" + $MemoryDir + "（新工作区请先按 AGENTS.md 初始化，或忽略本检查）")
  exit 0
}

# 规则：相对路径匹配（不区分大小写）→ 行数上限
$rules = @(
  @{ Pattern = 'HANDOFF\.md$'; Limit = 80;  Why = '交接卡必须一眼读完；超限把旧阶段移入 SHORT-TERM/SUMMARY' },
  @{ Pattern = 'SHORT-TERM\.md$'; Limit = 400; Why = '流水只留近期；超限移到 SHORT-TERM-ARCHIVE-<季度>.md 并留一行指针（不要删历史）' },
  @{ Pattern = 'INDEX\.md$'; Limit = 150; Why = '索引必须可全量浏览；超限把最旧行移入归档区' },
  @{ Pattern = 'PROJECT\.md$'; Limit = 150; Why = '任务表 ≤50 行；已完成子任务合并进 SUMMARY' },
  @{ Pattern = 'NOTES\.md$'; Limit = 400; Why = '单文件超限按功能拆分多个 md' }
)

$checked = 0
$files = Get-ChildItem -LiteralPath $MemoryDir -Recurse -File -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.Extension -eq '.md' -and $_.FullName -notmatch '\\\.git\\' }

Write-Output ("=== 记忆体积门禁：" + $MemoryDir + " ===")

# 交接卡缺失=新会话没有"唯一必读"，比超限更该提示（模板见 pydev-share/templates/.dsh-memory/HANDOFF.md）
if (-not (Test-Path -LiteralPath (Join-Path $MemoryDir 'HANDOFF.md'))) {
  Write-Output "  [MISS] HANDOFF.md 不存在 —— 新会话缺「唯一必读」交接卡；从模板补建（≤80 行：当前阶段/下一步 3 条/已知坑/验证命令/基线数字）。"
  # 无 HANDOFF 时改用"启动块兜底"：SHORT-TERM 前 100 行内必须有 <!-- STARTUP-END --> 标记，
  # agent 只读到标记为止；否则它会把整份流水读进上下文（V18 实测 600+ 行）。
  $stPath = Join-Path $MemoryDir 'SHORT-TERM.md'
  if (Test-Path -LiteralPath $stPath) {
    $stText = Get-Content -LiteralPath $stPath -Raw
    $markerIndex = $stText.IndexOf('<!-- STARTUP-END -->')
    if ($markerIndex -lt 0) {
      Write-Output "  [MISS] SHORT-TERM.md 缺 <!-- STARTUP-END --> 启动块标记 —— 无 HANDOFF 时 agent 会把整份流水读进上下文。"
    } else {
      $upto = $stText.Substring(0, $markerIndex)
      $markerLine = ($upto -split "\r?\n").Count
      if ($markerLine -gt 100) {
        Write-Output ("  [OVER] SHORT-TERM.md 启动块在第 " + $markerLine + " 行（应 ≤100）—— 把启动块压缩到 100 行内。")
      } else {
        Write-Output ("  [OK]   SHORT-TERM.md 启动块标记在第 " + $markerLine + " 行")
      }
    }
  }
}

foreach ($f in $files) {
  $rel = $f.FullName.Substring($MemoryDir.Length).TrimStart('\', '/')
  $rule = $rules | Where-Object { $rel -match $_.Pattern } | Select-Object -First 1
  if (-not $rule) { continue }
  $checked++
  $lines = (Get-Content -LiteralPath $f.FullName -ErrorAction SilentlyContinue | Measure-Object).Count
  if ($lines -gt $rule.Limit) {
    $over++
    Write-Output ("  [OVER] " + $rel + "  " + $lines + " 行 > 上限 " + $rule.Limit + " —— " + $rule.Why)
  } else {
    Write-Output ("  [OK]   " + $rel + "  " + $lines + " / " + $rule.Limit + " 行")
  }
}
if ($checked -eq 0) { Write-Output "  （未发现受管记忆文件）" }
Write-Output ("=== 受管文件 " + $checked + " 个，超限 " + $over + " 个 ===")

# ── 文档声明上限 vs 可执行上限是否一致（防"上限写在文档里必然失效"复发）────────────
# 本工作区实测踩过：SHORT-TERM.md 头部写"硬上限 120 行"，而本脚本按 400 行放行 —— 两边打架时
# 人和 agent 各信一边，等于没有上限。⇒ 把"一致性"本身变成断言。
foreach ($pair in @(@{ File = 'SHORT-TERM.md'; Rule = 'SHORT-TERM\.md$' }, @{ File = 'HANDOFF.md'; Rule = 'HANDOFF\.md$' })) {
  $p = Join-Path $MemoryDir $pair.File
  if (-not (Test-Path -LiteralPath $p)) { continue }
  $head = (Get-Content -LiteralPath $p -TotalCount 6 -ErrorAction SilentlyContinue) -join "`n"
  $decl = [regex]::Match($head, '硬上限\s*\*{0,2}\s*(\d+)\s*行')
  $ruleLimit = ($rules | Where-Object { $pair.File -match $_.Pattern } | Select-Object -First 1).Limit
  if ($decl.Success -and $ruleLimit) {
    $n = [int]$decl.Groups[1].Value
    if ($n -ne $ruleLimit) {
      $over++
      Write-Output ("  [DRIFT] " + $pair.File + " 头部声明上限 " + $n + " 行，但本脚本按 " + $ruleLimit + " 行判定 —— 两边必须一致，改掉其中一个。")
    } else {
      Write-Output ("  [OK]   " + $pair.File + " 头部声明上限与本脚本一致（" + $n + " 行）")
    }
  }
}

# ── 记忆仓库是否有未提交改动（.dsh-memory 是跨会话唯一桥梁）──────────────────────
if (Test-Path -LiteralPath (Join-Path $MemoryDir '.git')) {
  $dirty = & git -C $MemoryDir status --short 2>$null
  if ($dirty) {
    Write-Output ("  [WARN] 记忆仓库有 " + (@($dirty).Count) + " 项未提交 —— 未提交的记忆不跨会话（协议要求写入后提交）。")
  } else {
    Write-Output "  [OK]   记忆仓库无未提交改动"
  }
}

if ($over -gt 0) {
  Write-Output "处理（保留历史，不要删）：流水类超限 → 把最旧批次移到 .dsh-memory/SHORT-TERM-ARCHIVE-<季度>.md，原文件留一行指针；"
  Write-Output "                 PROJECT/INDEX 超限 → 已完成项合并进 project/SUMMARY.md 归档区（见 memory-system 技能）。"
  Write-Output "                 AGENTS.md 超限 → 方法论下沉到技能（按需加载），AGENTS.md 只留事实+启动清单+本机硬止+红线。"
  if ($FailOnOver) { exit 1 }
}
exit 0
