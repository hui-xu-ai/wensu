# tools/proj —— 项目工具（0.7.0 起为「依赖」而非「源码副本」）

本目录只保留三个启动器和一份 wheel；实现全部来自已安装的 `pydev-proj-core`。
**不要**再往这里拷 `proj_core/` 源码——那就是"每个项目各存一份、升级要挨个拷"的老路。

## 安装 / 升级

```powershell
python -m pip install --no-index --find-links tools\proj\wheels pydev-proj-core
```

- wheel 随模板放在 `tools\proj\wheels\`（离线可用，无需联网）。
- 升级：把新版 whl 放进 `wheels\`，重跑上面这条命令即可；`python tools\proj\proj.py --version` 应随之变化。
- 装到哪个解释器，就用哪个解释器跑：CI 用 venv 时在 venv 里装；本机 PATH 的 python 也装一份，`quality-gate.ps1` 走的是 PATH。

## 常用

```powershell
python tools\proj\proj.py --version
python tools\proj\proj.py silent .                  # 裸 except / 吞异常 / 静默降级
python tools\proj\proj.py silent . --baseline tools\silent-baseline.json   # 存量项目棘轮
python tools\proj\proj.py split-check . --src-rev HEAD                     # 拆分等价性
python tools\proj\proj.py panel start . --port 8787
```

## 约定

- 版本以 `python tools\proj\proj.py --version` 为准（不要手写进文档）。
- `quality-gate.ps1` 的 G8 依赖 `proj silent --json`；baseline 若存在则只拦增量。
