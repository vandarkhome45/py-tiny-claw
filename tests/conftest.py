"""pytest 路径引导。

把项目根目录追加到 sys.path 的**末尾**，而不是最前面。

原因：本项目根目录下有一个 cmd/ 包，与 Python 标准库的 cmd 模块同名。
若项目根目录被插到 sys.path 最前面（例如使用 pythonpath = ["."]，
或用 python -m pytest 启动），cmd/ 就会遮蔽标准库 cmd 模块，
而 pytest 自身依赖 pdb -> cmd.Cmd，会立即抛出 AttributeError 崩溃。

追加到末尾后：stdlib 优先命中 cmd，本项目的 internal / cmd.claw 也仍可导入。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))
