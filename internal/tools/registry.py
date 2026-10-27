# internal/tools/registry.py
# 对应 Go 版: internal/tools/registry.go
# 第 5 章：Registry 从接口升级为真实实现，负责工具的注册、查找与统一执行。
import logging
from abc import ABC, abstractmethod

from internal.schema.message import ToolCall, ToolDefinition, ToolResult

log = logging.getLogger(__name__)


class BaseTool(ABC):
    """所有工具必须实现的基础接口（对应 Go 的 BaseTool interface）"""

    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def definition(self) -> ToolDefinition:
        ...

    @abstractmethod
    def execute(self, args: str) -> str:
        """args 为原始 JSON 字符串，由工具自行解析；执行失败时抛出异常（对应 Go 的返回 error）"""
        ...


class Registry(ABC):
    """工具注册中心接口"""

    @abstractmethod
    def register(self, tool: BaseTool):
        ...

    @abstractmethod
    def get_available_tools(self) -> list[ToolDefinition]:
        ...

    @abstractmethod
    def execute(self, call: ToolCall) -> ToolResult:
        ...


class RegistryImpl(Registry):
    """Registry 的默认实现：内部用一个 dict 存储 名称 -> 工具实例 的映射"""

    def __init__(self):
        self.tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        # 职责 1：动态挂载（Register）
        tool_name = tool.name()

        if tool_name in self.tools:
            print(f"[Warning] 工具 '{tool_name}' 已经被注册，将被覆盖。")

        self.tools[tool_name] = tool
        print(f"[Registry] 成功挂载工具: {tool_name}")

    def get_available_tools(self) -> list[ToolDefinition]:
        # 职责 2：描述暴露（Expose Schema）
        return [tool.definition() for tool in self.tools.values()]

    def execute(self, call: ToolCall) -> ToolResult:
        # 职责 3：路由分发与执行（Dispatch & Execute）
        tool = self.tools.get(call.name)

        if tool is None:
            return ToolResult(
                tool_call_id=call.id,
                output=f"Error: 系统中不存在名为 '{call.name}' 的工具。",
                is_error=True,
            )

        try:
            output = tool.execute(call.arguments)
        except Exception as e:
            # 关键防线：任何工具异常都在此转换为错误结果，绝不让引擎崩溃
            return ToolResult(
                tool_call_id=call.id,
                output=f"Error executing {call.name}: {e}",
                is_error=True,
            )

        return ToolResult(tool_call_id=call.id, output=output, is_error=False)


def new_registry() -> Registry:
    """对应 Go 版的 NewRegistry 构造函数"""
    return RegistryImpl()
