import importlib.util
from pathlib import Path

from internal.schema.message import ToolCall

MAIN_PATH = Path(__file__).parents[1] / "cmd" / "claw" / "main.py"
SPEC = importlib.util.spec_from_file_location("py_tiny_claw_main", MAIN_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("无法加载 cmd/claw/main.py")
MAIN_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MAIN_MODULE)
MockRegistry = MAIN_MODULE.MockRegistry


def test_mock_registry_defines_weather_tool():
    registry = MockRegistry()

    tools = registry.get_available_tools()

    assert len(tools) == 1
    assert tools[0].name == "get_weather"
    assert tools[0].description == "获取指定城市的当前天气情况。"
    assert tools[0].input_schema["required"] == ["city"]
    assert tools[0].input_schema["properties"]["city"]["type"] == "string"


def test_mock_registry_returns_weather_result():
    registry = MockRegistry()
    call = ToolCall(
        id="call_weather",
        name="get_weather",
        arguments='{"city":"北京"}',
    )

    result = registry.execute(call)

    assert result.tool_call_id == "call_weather"
    assert result.output == "API 返回：今天是晴天，气温 25 度。"
    assert result.is_error is False
