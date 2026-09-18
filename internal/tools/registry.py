# internal/tools/registry.py
# 对应 Go 版: internal/tools/registry.go
# 第 2 章：此时 Registry 还只是⼀个接⼝定义，具体实现由 main.py 中的 mock 提供。
from abc import ABC, abstractmethod
from internal.schema.message import ToolCall, ToolDefinition, ToolResult
class Registry(ABC):
 """⼯具注册中⼼接⼝（对应 Go 的 interface）"""
 @abstractmethod
 def get_available_tools(self) -> list[ToolDefinition]:
    ...
 @abstractmethod
 def execute(self, call: ToolCall) -> ToolResult:
    ...