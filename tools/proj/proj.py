#!/usr/bin/env python3
r"""proj 启动器（项目侧不再携带源码）。

优先使用已安装的 `pydev-proj-core`；未安装时给出离线安装命令。
安装（wheel 已随模板放在 tools\proj\wheels\）：

    python -m pip install --no-index --find-links tools\proj\wheels pydev-proj-core

升级：换掉 wheels\ 里的 whl 后重跑上面这条命令。
"""
import sys
from pathlib import Path


def _main() -> int:
    try:
        from proj_core.cli import main
    except ImportError:
        wheels = Path(__file__).resolve().parent / "wheels"
        print("未安装 pydev-proj-core。安装：\n"
              f'  python -m pip install --no-index --find-links "{wheels}" pydev-proj-core',
              file=sys.stderr)
        return 2
    return main()


if __name__ == "__main__":
    raise SystemExit(_main())
