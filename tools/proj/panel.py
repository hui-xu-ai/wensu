#!/usr/bin/env python3
"""项目看板启动器（实现随 pydev-proj-core 安装，项目不再携带源码）。"""
import sys
from pathlib import Path


def _main() -> int:
    try:
        from proj_core.panel import main
    except ImportError:
        wheels = Path(__file__).resolve().parent / "wheels"
        print(f'未安装 pydev-proj-core：python -m pip install --no-index --find-links "{wheels}" pydev-proj-core',
              file=sys.stderr)
        return 2
    return main()


if __name__ == "__main__":
    raise SystemExit(_main())
