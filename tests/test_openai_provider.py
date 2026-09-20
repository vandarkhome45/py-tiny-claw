from types import SimpleNamespace

import openai
import pytest

from internal.provider.openai import (
    OpenAIProvider,
    new_deepseek_provider,
)
from internal.schema.message import (
    Message,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_USER,
    ToolCall,
    ToolDefinition,
)


class FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.params = None

    def create(self, **params):
        self.params = params
        return self.response


class FakeClient:
    def __init__(self, response):
        self.completions = FakeCompletions(response)
        self.chat = SimpleNamespace(completions=self.completions)


def test_generate_converts_messages_tools_and_response():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="我来查询天气",
                    tool_calls=[
                        SimpleNamespace(
                            id="call_weather",
                            type="function",
                            function=SimpleNamespace(
                                name="get_weather",
                                arguments='{"city":"北京"}',
                            ),
                        )
                    ],
                )
            )
        ]
    )
    client = FakeClient(response)
    provider = OpenAIProvider(client, "deepseek-chat")

    messages = [
        Message(role=ROLE_SYSTEM, content="system prompt"),
        Message(role=ROLE_USER, content="查询北京天气"),
        Message(
            role=ROLE_ASSISTANT,
            content="正在查询",
            tool_calls=[
                ToolCall(
                    id="call_weather",
                    name="get_weather",
                    arguments='{"city":"北京"}',
                )
            ],
        ),
        Message(
            role=ROLE_USER,
            content="晴天，25 度",
            tool_call_id="call_weather",
        ),
    ]
    tools = [
        ToolDefinition(
            name="get_weather",
            description="获取指定城市的当前天气情况。",
            input_schema={
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        )
    ]

    result = provider.generate(messages, tools)

    assert client.completions.params["model"] == "deepseek-chat"
    assert client.completions.params["messages"][0] == {
        "role": "system",
        "content": "system prompt",
    }
    assert client.completions.params["messages"][2]["tool_calls"] == [
        {
            "id": "call_weather",
            "type": "function",
            "function": {
                "name": "get_weather",
                "arguments": '{"city":"北京"}',
            },
        }
    ]
    assert client.completions.params["messages"][3] == {
        "role": "tool",
        "content": "晴天，25 度",
        "tool_call_id": "call_weather",
    }
    assert client.completions.params["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "获取指定城市的当前天气情况。",
                "parameters": tools[0].input_schema,
            },
        }
    ]
    assert result.role == ROLE_ASSISTANT
    assert result.content == "我来查询天气"
    assert result.tool_calls == [
        ToolCall(
            id="call_weather",
            name="get_weather",
            arguments='{"city":"北京"}',
        )
    ]


def test_generate_omits_tools_when_none_are_available():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="直接回答", tool_calls=None)
            )
        ]
    )
    client = FakeClient(response)
    provider = OpenAIProvider(client, "deepseek-chat")

    result = provider.generate([Message(role=ROLE_USER, content="你好")])

    assert "tools" not in client.completions.params
    assert result.content == "直接回答"
    assert result.tool_calls == []


def test_new_deepseek_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        new_deepseek_provider("deepseek-chat")


def test_new_deepseek_provider_configures_openai_client(monkeypatch):
    captured = {}

    def fake_openai_client(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(openai, "OpenAI", fake_openai_client)

    provider = new_deepseek_provider("deepseek-chat")

    assert captured == {
        "api_key": "test-key",
        "base_url": "https://api.deepseek.com",
    }
    assert provider.model == "deepseek-chat"
