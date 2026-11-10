# internal/tools/bash.py
# 对应 Go 版: internal/tools/bash.go
# 第 6 章：bash 工具 —— Agent 最强大的"万能手"，可以执行任意 shell 命令。
import json
import os
import subprocess

from internal.schema.message import ToolDefinition
from internal.tools.registry import BaseTool

# 单次命令的最长执行时间（秒）
TIMEOUT_SECONDS = 30
# 回传给模型的输出上限（字符），防止上下文爆炸
MAX_OUTPUT_CHARS = 8000


class BashTool(BaseTool):
    def __init__(self, work_dir: str):
        self.work_dir = work_dir

    def name(self) -> str:
        return "bash"

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name(),
            description="在当前工作区执行任意的 bash 命令。支持链式命令(如 &&)。返回标准输出(stdout)和标准错误(stderr)。",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的 bash 命令",
                    },
                },
                "required": ["command"],
            },
        )

    def execute(self, args: str) -> str:
        try:
            input_args = json.loads(args)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"参数解析失败: {e}") from e

        command = input_args.get("command", "")

        # 边界 1：工作区约束（cwd）+ 边界 2：超时控制（timeout=30s）
        # 安全加固：最小化 env，模型无法通过 env/cat ~/.zshrc 等读到 API 密钥
        try:
            completed = subprocess.run(
                ["bash", "-c", command],
                cwd=self.work_dir,
                env=_safe_env(),
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as e:
            # 超时不算"异常"，把已有输出连同警告一起回传，让模型自己决定下一步
            partial = _merge_output(e.stdout, e.stderr)
            return _truncate(
                partial
                + f"\n[警告: 命令执行超时({TIMEOUT_SECONDS}s)，已被系统强制终止。]"
            )

        output = _merge_output(completed.stdout, completed.stderr)

        # 边界 3：自纠错回传 —— 非零退出码原样回传，而不是抛异常
        if completed.returncode != 0:
            return _truncate(
                f"执行报错: exit status {completed.returncode}\n输出:\n{output}"
            )

        # 边界 4：输出为空时的明确提示
        if output.strip() == "":
            return "命令执行成功，无终端输出。"

        return _truncate(output)


def _safe_env() -> dict:
    """安全加固：只继承白名单环境变量，防止 API Key 等机密经 bash 泄漏进上下文。"""
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR", "USER", "SHELL")
    return {k: os.environ[k] for k in keep if k in os.environ}


def _merge_output(stdout, stderr) -> str:
    """合并 stdout/stderr；超时路径下可能拿到 bytes，统一解码为 str。"""
    parts = []
    for chunk in (stdout, stderr):
        if chunk is None:
            continue
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8", errors="replace")
        parts.append(chunk)
    return "".join(parts)


def _truncate(text: str) -> str:
    """边界 5：输出超过 8000 字符时截断，并追加截断提示。"""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return (
        f"{text[:MAX_OUTPUT_CHARS]}"
        f"\n\n...[输出过长，已被系统截断至前 {MAX_OUTPUT_CHARS} 字符]..."
    )
