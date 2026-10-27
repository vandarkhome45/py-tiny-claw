# internal/tools/read_file.py
# 对应 Go 版: internal/tools/read_file.go
# 第 5 章：第一个真实工具 —— 读取工作区内的文件。
import json
import os

from internal.schema.message import ToolDefinition
from internal.tools.registry import BaseTool


class ReadFileTool(BaseTool):
    def __init__(self, work_dir: str):
        self.work_dir = work_dir

    def name(self) -> str:
        return "read_file"

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name(),
            description="读取指定路径的文件内容。请提供相对工作区的路径。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要读取的文件路径，如 cmd/claw/main.py",
                    },
                },
                "required": ["path"],
            },
        )

    def execute(self, args: str) -> str:
        try:
            input_args = json.loads(args)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"参数解析失败: {e}") from e

        full_path = os.path.join(self.work_dir, input_args.get("path", ""))

        try:
            with open(full_path, "rb") as f:
                content = f.read()
        except OSError as e:
            raise RuntimeError(f"打开文件失败: {e}") from e

        # 防御上下文爆炸：超长文件只保留前 8000 字节
        MAX_LEN = 8000
        if len(content) > MAX_LEN:
            truncated_msg = (
                f"{content[:MAX_LEN].decode('utf-8', errors='replace')}"
                f"\n\n...[由于内容过长，已被系统截断至前 {MAX_LEN} 字节]..."
            )
            return truncated_msg

        return content.decode("utf-8", errors="replace")
