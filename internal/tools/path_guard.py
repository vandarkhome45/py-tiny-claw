# internal/tools/path_guard.py
# 安全加固：统一的工作区路径守卫。
# 防两类穿越：
#   1) 相对路径逃逸，如 ../../.zshrc
#   2) 绝对路径整体覆盖前缀，如 os.path.join(ws, "/etc/passwd") == "/etc/passwd"
import os


def resolve_in_workspace(work_dir: str, rel_path: str) -> str:
    """把工具传入的路径解析到真实绝对路径，并强制其位于工作区内。

    越界一律抛 RuntimeError，绝不返回工作区外的路径。
    """
    if not rel_path or not rel_path.strip():
        raise RuntimeError("路径不能为空")

    real_work_dir = os.path.realpath(work_dir)
    full_path = os.path.realpath(os.path.join(real_work_dir, rel_path))

    # commonpath 判定前缀归属：越界（含穿越与绝对路径注入）直接拒绝
    if os.path.commonpath([full_path, real_work_dir]) != real_work_dir:
        raise RuntimeError(f"路径越出工作区，已拒绝: {rel_path}")

    return full_path
