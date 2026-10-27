import json

from internal.schema.message import ToolCall, ToolDefinition
from internal.tools.registry import BaseTool, new_registry


class EchoTool(BaseTool):
    def name(self) -> str:
        return "echo"

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name(),
            description="回显传入的文本",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )

    def execute(self, args: str) -> str:
        return "echo: " + json.loads(args)["text"]


class BoomTool(BaseTool):
    def name(self) -> str:
        return "boom"

    def definition(self) -> ToolDefinition:
        return ToolDefinition(name=self.name(), description="总是抛异常", input_schema={})

    def execute(self, args: str) -> str:
        raise ValueError("工具内部炸了")


def test_register_then_expose_schema():
    registry = new_registry()
    registry.register(EchoTool())

    tools = registry.get_available_tools()

    assert [t.name for t in tools] == ["echo"]
    assert tools[0].input_schema["required"] == ["text"]


def test_register_duplicate_warns_and_overwrites(capsys):
    registry = new_registry()
    registry.register(EchoTool())
    registry.register(EchoTool())

    out = capsys.readouterr().out
    assert "已经被注册" in out
    # 覆盖而非追加，工具数量仍是 1
    assert len(registry.get_available_tools()) == 1


def test_execute_unknown_tool_returns_error_result():
    registry = new_registry()

    result = registry.execute(ToolCall(id="call_1", name="delete_all", arguments="{}"))

    assert result.is_error is True
    assert "delete_all" in result.output
    assert result.tool_call_id == "call_1"


def test_execute_success_returns_output_and_id():
    registry = new_registry()
    registry.register(EchoTool())

    result = registry.execute(
        ToolCall(id="call_2", name="echo", arguments='{"text":"你好"}')
    )

    assert result.is_error is False
    assert result.output == "echo: 你好"
    assert result.tool_call_id == "call_2"


def test_execute_swallows_tool_exception():
    """工具抛异常时必须被兜底成 is_error 结果，绝不能让引擎崩溃。"""
    registry = new_registry()
    registry.register(BoomTool())

    result = registry.execute(ToolCall(id="call_3", name="boom", arguments="{}"))

    assert result.is_error is True
    assert "工具内部炸了" in result.output
    assert result.tool_call_id == "call_3"
