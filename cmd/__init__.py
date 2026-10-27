"""py-tiny-claw 的命令行入口包。

包名冲突说明（重要）
--------------------
本包名 ``cmd`` 与 Python 标准库的 ``cmd`` 模块同名：

* 为了让 ``python -m cmd.claw.main`` 可用，本目录必须保留 ``__init__.py``；
* 但项目根目录一旦被放到 ``sys.path`` 的最前面（例如 ``python -m pytest``），
  本包就会遮蔽标准库 ``cmd``，而 pytest 内部依赖 ``pdb`` → ``cmd.Cmd``，
  会直接抛 ``AttributeError: module 'cmd' has no attribute 'Cmd'``。

下面的兼容处理把标准库 ``cmd.py`` 的公开成员补进本包命名空间，
使仍然依赖标准库 ``cmd`` 的第三方代码（pdb 等）可以正常工作。
"""
import importlib.util as _importlib_util
import os as _os
import sys as _sys
import sysconfig as _sysconfig


def _reexport_stdlib_cmd() -> None:
    """按文件路径加载标准库的 cmd.py，并把其公开成员并入本包。"""
    candidates = [
        _os.path.join(_sysconfig.get_paths().get("stdlib") or "", "cmd.py"),
        _os.path.join(_os.path.dirname(_os.__file__), "cmd.py"),
    ]

    for path in candidates:
        if not path or not _os.path.isfile(path):
            continue
        try:
            spec = _importlib_util.spec_from_file_location("_stdlib_cmd_compat", path)
            if spec is None or spec.loader is None:
                continue
            module = _importlib_util.module_from_spec(spec)
            _sys.modules[spec.name] = module
            spec.loader.exec_module(module)
        except Exception:
            continue

        for key, value in vars(module).items():
            if not key.startswith("__"):
                globals().setdefault(key, value)
        return


_reexport_stdlib_cmd()
