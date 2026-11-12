#!/usr/bin/env python3
"""bootstrap-project.py —— pydev 项目的初始化门与最小记忆脚手架（零第三方依赖）。

为什么存在：`.dsh-memory/`、`tools/memory-gate.ps1`、AGENTS.md 的 HANDOFF 指针
在旧流程里**没有任何时刻会创建**——阶段 0 假设它们已存在，缺失会静默自我延续。

用法：
    python tools/bootstrap-project.py . --check          # 初始化门（只读，缺什么报什么）
    python tools/bootstrap-project.py . --apply          # 建最小集（不覆盖已有文件）
    python tools/bootstrap-project.py . --apply --full   # 最小集 + PROJECT/SUMMARY/LESSONS/DECISIONS/EXPERIENCE

模板来源：优先用脚本同级的 `templates/.dsh-memory`（预设分发形态）；
找不到就用脚本内置骨架（任意项目可独立运行）。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:  # Windows 控制台默认 cp936；统一 UTF-8，避免中文乱码
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001, S110 - 老 Python / 非标准流  # silent-ok: 控制台编码失败不影响功能
        pass

LIMITS = {
    "HANDOFF.md": 80,
    "INDEX.md": 150,
    "SHORT-TERM.md": 400,
    "project/PROJECT.md": 150,
}
REQUIRED = ["HANDOFF.md", "INDEX.md", "SHORT-TERM.md",
            "project/CODE_MAP.md", "project/ARCHITECTURE.md"]
OPTIONAL = ["project/PROJECT.md", "project/SUMMARY.md",
            "LONG-TERM/LESSONS.md", "LONG-TERM/DECISIONS.md", "LONG-TERM/EXPERIENCE.md"]

HANDOFF = """# 交接卡（HANDOFF）

> 新会话唯一必读（硬上限 80 行）：当前阶段 / 下一步 3 条 / 已知坑 / 验证命令 / 基线数字。
> 维护：子任务完成或会话收尾时整篇重写；被挤出的旧内容进 SHORT-TERM 或 SUMMARY。

## 当前阶段
（未开始）

## 下一步（最多 3 条，按优先级）
1. （暂无）
2. （暂无）
3. （暂无）

## 已知坑
（暂无 —— 每条一行：现象 + 规避方式）

## 验证命令
```powershell
# 一条最便宜的“确认没坏”命令
```

## 基线数字
| 指标 | 当前值 |
|---|---|
| 测试 | （未跑） |
| 关键产物 | （无） |
"""

INDEX = """# 记忆索引（INDEX）

> 硬上限 150 行。长期条目各一行：ID | 日期 | 主题 | 关键结论 | 文件:行号。
> 新增/归档条目时同步增删本表。

（暂无）
"""

SHORT_TERM = """# 短期记忆（SHORT-TERM）· 近期流水

> 硬上限 400 行；超限把旧批次移入 project/SUMMARY.md 归档区并留一行指针。
> 新会话不必读本文件——先读 HANDOFF。

## 当前目标
（暂无）

## 近期流水
- （暂无）
"""

CODE_MAP = """# 代码地图（CODE_MAP）

> 文件/模块 → 职责 → 关键类/函数 → 被谁调用。新增或修改模块时增量更新一行。

| 文件/模块 | 职责 | 关键类/函数 | 被谁调用 | 最近更新 |
|---|---|---|---|---|
| （待填写） | | | | |
"""

ARCHITECTURE = """# 整体架构（ARCHITECTURE）

> 模块划分、职责、数据流与接口；架构变更与 CODE_MAP 同提交更新。

## 技术栈
（待填写）

## 模块与数据流
（待填写）
"""

PROJECT = """# 项目任务表（PROJECT）

> 当前子任务与状态；整文件 ≤150 行，任务表 ≤50 行。完成项移入 SUMMARY。

| 编号 | 子任务 | 状态 | 验收 |
|---|---|---|---|
| — | （暂无） | | |
"""

SUMMARY = """# 项目总结与归档（SUMMARY）

> 被上列文件挤出的旧内容进这里；里程碑记一行 token 成本大头。
"""

LESSONS = """# 历史教训（LESSONS）

> 追加式；每条：`- YYYY-MM-DD | 场景 | 根因 | 解决 | 可复用教训`。
"""

DECISIONS = """# 架构决策（DECISIONS）

> 每条含：背景 / 决策 / 理由 / 被否的替代方案及原因。
"""

EXPERIENCE = """# 有益经验（EXPERIENCE）

> 追加式；只记可复用的做法。
"""

PROJECT_AGENTS = """# 工作区说明（pydev 项目）

## 会话开始
1. 读 `.dsh-memory/HANDOFF.md`（≤80 行，唯一必读）。
2. 跑 `python tools\\bootstrap-project.py . --check`（没有脚本时手工核对 4 个记忆文件上限）。
3. 加载 `pydev-protocol` 技能，再按任务加载其余技能。

## 记忆
- 状态变化定点更新 HANDOFF；流水写 SHORT-TERM；教训/决策登记 INDEX。
- 上限：HANDOFF 80 / INDEX 150 / SHORT-TERM 400 / PROJECT 150 行；超限先归档。
- `.dsh-memory/` 是独立 git 仓库，不随代码提交。

## 硬止
- 删改用户文件先列清单；不按进程名杀浏览器；不重启 Harness。
- 提交禁止 `git add -A`，显式列路径。

## 门序
G0 需求 → G1 设计/契约 → G2 计划 → G3 实现 → G4 验证 → G5 评审 → G6 发布（见 `pydev-protocol`）。
"""

STANDARDS = """# 门与标准索引（权威清单）

> 新增标准：本表加一行，并落 `docs/standards/`。技能只引用编号，不抄全文。

| 编号 | 名称 | 位置 |
|---|---|---|
| G0 | 需求 | `work/tasks/<id>/intake.md` |
| G1 | 设计 / 契约 | `docs/adr/NNN.md` |
| G2 | 计划 | `work/tasks/<id>/plan.md` |
| G3 | 实现 / 测试 | 代码 + 测试提交 |
| G4 | 验证 | `work/verify/<run-id>/RESULT.md` |
| G5 | 评审 | 评审记录 |
| G6 | 发布 | CHANGELOG + 回滚 |
"""

GITIGNORE_LINES = [".dsh-memory/", "work/", "local/", "logs/", "tmp/", "out/",
                   "feedback/", "__pycache__/", ".venv/", ".pytest_cache/",
                   "node_modules/", "*.log", ".env"]


def find_templates(script: Path, explicit: str | None) -> Path | None:
    cands: list[Path] = []
    if explicit:
        cands.append(Path(explicit))
    cands += [script.parent.parent, script.parent.parent / "pydev-share" / "templates",
              Path.cwd() / "pydev-share" / "templates"]
    for c in cands:
        t = c / "templates" if (c / "templates" / ".dsh-memory").is_dir() else c
        if (t / ".dsh-memory").is_dir():
            return t
    return None


def embedded(rel: str) -> str:
    return {
        "HANDOFF.md": HANDOFF, "INDEX.md": INDEX, "SHORT-TERM.md": SHORT_TERM,
        "project/CODE_MAP.md": CODE_MAP, "project/ARCHITECTURE.md": ARCHITECTURE,
        "project/PROJECT.md": PROJECT, "project/SUMMARY.md": SUMMARY,
        "LONG-TERM/LESSONS.md": LESSONS, "LONG-TERM/DECISIONS.md": DECISIONS,
        "LONG-TERM/EXPERIENCE.md": EXPERIENCE, "project-AGENTS.md": PROJECT_AGENTS,
        "docs/standards/INDEX.md": STANDARDS,
    }[rel]


def template_text(templates: Path | None, rel: str) -> str:
    if templates is not None:
        p = templates / ".dsh-memory" / rel
        if rel == "project-AGENTS.md":
            p = templates / "project-AGENTS.md"
        elif rel == "docs/standards/INDEX.md":
            p = templates / "docs" / "standards" / "INDEX.md"
        if p.is_file():
            return p.read_text(encoding="utf-8")
    return embedded(rel)


def write_missing(path: Path, text: str, created: list[str], skipped: list[str]) -> None:
    if path.exists():
        skipped.append(str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    created.append(str(path))


def ensure_gitignore(root: Path, created: list[str], skipped: list[str]) -> None:
    p = root / ".gitignore"
    if p.exists():
        # 已有项目只补记忆目录这一条：盲目追加 work/ 等会与已跟踪路径冲突
        text = p.read_text(encoding="utf-8", errors="replace")
        if ".dsh-memory/" in text.splitlines():
            skipped.append(str(p))
            return
        p.write_text(text.rstrip() + "\n.dsh-memory/\n", encoding="utf-8")
        created.append(str(p) + " (append .dsh-memory/)")
    else:
        p.write_text("\n".join(GITIGNORE_LINES) + "\n", encoding="utf-8")
        created.append(str(p))


def ensure_agents(root: Path, templates: Path | None, created: list[str], skipped: list[str]) -> None:
    p = root / "AGENTS.md"
    if not p.exists():
        p.write_text(template_text(templates, "project-AGENTS.md"), encoding="utf-8")
        created.append(str(p))
        return
    text = p.read_text(encoding="utf-8", errors="replace")
    if ".dsh-memory" in text and "HANDOFF" in text:
        skipped.append(str(p) + " (已有记忆指针)")
        return
    block = ("\n## 会话记忆（pydev，bootstrap 追加）\n\n"
             "- 开局读 `.dsh-memory/HANDOFF.md`（≤80 行，唯一必读）；超限跑 "
             "`python tools\\bootstrap-project.py . --check`。\n")
    p.write_text(text.rstrip() + "\n" + block, encoding="utf-8")
    created.append(str(p) + " (追加记忆指针)")


def copy_tools(root: Path, templates: Path | None, script: Path,
               created: list[str], skipped: list[str]) -> None:
    tools = root / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    dst_self = tools / "bootstrap-project.py"
    if not dst_self.exists() and script.resolve() != dst_self.resolve():
        shutil.copy2(script, dst_self)
        created.append(str(dst_self))
    if templates is not None:
        src = templates / "tools"
        for name in ("memory-gate.ps1",):
            if (src / name).is_file() and not (tools / name).exists():
                shutil.copy2(src / name, tools / name)
                created.append(str(tools / name))
        if (src / "proj").is_dir() and not (tools / "proj").exists():
            shutil.copytree(src / "proj", tools / "proj")
            created.append(str(tools / "proj"))
    git_init(root / ".dsh-memory", created)


def git_init(mem: Path, created: list[str]) -> None:
    if (mem / ".git").exists():
        return
    try:
        subprocess.run(["git", "init", "-q", str(mem)], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        created.append(str(mem / ".git") + " (git init)")
    except OSError:  # silent-ok: 无 git 时跳过初始化，不阻断 bootstrap
        pass


def line_count(p: Path) -> int:
    return len(p.read_text(encoding="utf-8", errors="replace").splitlines())


def do_check(root: Path) -> int:
    mem = root / ".dsh-memory"
    print(f"=== bootstrap --check：{root}")
    fails = warns = 0
    for rel in REQUIRED:
        p = mem / rel
        if p.is_file():
            print(f"  [OK]   .dsh-memory/{rel}")
        else:
            print(f"  [MISS] .dsh-memory/{rel}")
            fails += 1
    for rel, limit in LIMITS.items():
        p = mem / rel
        if p.is_file():
            n = line_count(p)
            state = "[OVER]" if n > limit else "[OK]  "
            print(f"  {state} {rel}  {n} / {limit}")
            if n > limit:
                fails += 1
    agents = root / "AGENTS.md"
    if agents.is_file() and ".dsh-memory" in agents.read_text(encoding="utf-8", errors="replace"):
        print("  [OK]   AGENTS.md 含 .dsh-memory 指针")
    else:
        print("  [WARN] AGENTS.md 缺 .dsh-memory / HANDOFF 指针")
        warns += 1
    gi = root / ".gitignore"
    if gi.is_file() and ".dsh-memory/" in gi.read_text(encoding="utf-8", errors="replace"):
        print("  [OK]   .gitignore 排除 .dsh-memory/")
    else:
        print("  [WARN] .gitignore 未排除 .dsh-memory/")
        warns += 1
    if (root / "tools" / "proj").is_dir() or (root / "tools" / "proj.py").is_file():
        print("  [OK]   tools/proj 就位")
    else:
        print("  [WARN] tools/proj 缺失（可用全局 proj；或 bootstrap --apply 时从模板复制）")
        warns += 1
    std = root / "docs" / "standards" / "INDEX.md"
    std_ok = std.is_file()
    print("  [OK]   docs/standards/INDEX.md" if std_ok else
          "  [WARN] docs/standards/INDEX.md 缺失（可选，--apply 会建 starter）")
    warns += 0 if std_ok else 1
    print(f"\n=== 汇总：FAIL={fails}  WARN={warns}")
    return 1 if fails else 0


def do_apply(root: Path, templates: Path | None, script: Path, full: bool) -> int:
    mem = root / ".dsh-memory"
    created: list[str] = []
    skipped: list[str] = []
    rels = list(REQUIRED) + (OPTIONAL if full else [])
    for rel in rels:
        write_missing(mem / rel, template_text(templates, rel), created, skipped)
    write_missing(mem / ".gitignore", "*.tmp\n*.log\n", created, skipped)
    ensure_agents(root, templates, created, skipped)
    ensure_gitignore(root, created, skipped)
    write_missing(root / "docs" / "standards" / "INDEX.md",
                  template_text(templates, "docs/standards/INDEX.md"), created, skipped)
    copy_tools(root, templates, script, created, skipped)
    print(f"=== bootstrap --apply：{root}（{'full' if full else 'minimal'}）")
    for c in created:
        print(f"  [NEW]  {c}")
    print(f"  created={len(created)}  skipped={len(skipped)}（不覆盖已有文件）")
    print("\n下一步：读 .dsh-memory/HANDOFF.md 填写当前阶段；然后跑 --check 确认全 PASS。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="pydev 项目初始化门 / 最小记忆脚手架")
    ap.add_argument("root", nargs="?", default=".", help="项目根（默认当前目录）")
    ap.add_argument("--check", action="store_true", help="只检查（初始化门），不写文件")
    ap.add_argument("--apply", action="store_true", help="创建缺失文件（不覆盖已有）")
    ap.add_argument("--full", action="store_true", help="同时建 PROJECT/SUMMARY/LESSONS/DECISIONS/EXPERIENCE")
    ap.add_argument("--templates", default=None, help="模板目录（默认自动探测）")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"root 不存在：{root}", file=sys.stderr)
        return 2
    script = Path(__file__).resolve()
    templates = find_templates(script, args.templates)
    if args.check:
        return do_check(root)
    if args.apply:
        return do_apply(root, templates, script, args.full)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
