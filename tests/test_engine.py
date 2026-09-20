import logging

from internal.engine.loop import AgentEngine
from internal.schema.message import Message, ToolCall, ToolDefinition


class FakeProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def generate(self, messages, available_tools):
        self.calls.append((list(messages), available_tools))
        return next(self.responses)


class FakeRegistry:
    def __init__(self):
        self.tool = ToolDefinition(
            name="get_weather",
            description="获取指定城市的当前天气情况。",
            input_schema={
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        )

    def get_available_tools(self):
        return [self.tool]

    def execute(self, call):
        from internal.schema.message import ToolResult

        return ToolResult(
            tool_call_id=call.id,
            output="API 返回：今天是晴天，气温 25 度。",
            is_error=False,
        )


def make_tool_call_response():
    return Message(
        role="assistant",
        content="我来查询北京天气",
        tool_calls=[
            ToolCall(
                id="call_weather",
                name="get_weather",
                arguments='{"city":"北京"}',
            )
        ],
    )


def test_thinking_enabled_adds_phase_one_before_every_action(caplog):
    provider = FakeProvider(
        [
            Message(role="assistant", content="先查询天气。"),
            make_tool_call_response(),
            Message(role="assistant", content="根据结果给出建议。"),
            Message(role="assistant", content="北京适合跑步。"),
        ]
    )
    registry = FakeRegistry()
    engine = AgentEngine(provider, registry, ".", True)

    with caplog.at_level(logging.INFO):
        engine.run("我想去北京跑步，帮我查查天气适合吗？")

    assert len(provider.calls) == 4
    assert provider.calls[0][1] is None
    assert provider.calls[1][1] == [registry.tool]
    assert provider.calls[2][1] is None
    assert provider.calls[3][1] == [registry.tool]
    assert provider.calls[2][0][-1].content == "API 返回：今天是晴天，气温 25 度。"
    assert "[Engine][Phase 1]" in caplog.text
    assert "慢思考模式 (Thinking Phase): True" in caplog.text


def test_thinking_disabled_goes_straight_to_phase_two(caplog):
    provider = FakeProvider(
        [
            make_tool_call_response(),
            Message(role="assistant", content="北京适合跑步。"),
        ]
    )
    registry = FakeRegistry()
    engine = AgentEngine(provider, registry, ".", False)

    with caplog.at_level(logging.INFO):
        engine.run("我想去北京跑步，帮我查查天气适合吗？")

    assert len(provider.calls) == 2
    assert provider.calls[0][1] == [registry.tool]
    assert provider.calls[1][1] == [registry.tool]
    assert "[Engine][Phase 1]" not in caplog.text
    assert "慢思考模式 (Thinking Phase): False" in caplog.text
