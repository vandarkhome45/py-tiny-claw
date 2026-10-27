"""ClaudeProvider 的消息/工具格式转换测试。

claude.py 依赖 anthropic SDK；未安装时整个模块跳过，
装上之后（cd 项目根目录执行 uv sync）即会自动生效。
"""
import json

import pytest

anthropic = pytest.importorskip("anthropic")

from internal.provider.claude import ClaudeProvider
from internal.schema.message import (
    Message,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_USER,
    ToolCall,
    ToolDefinition,
)


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.params = None

    def create(self, **params):
        self.params = params
        return self.response


class FakeClient:
    def __init__(self, response):
        self.messages = FakeMessages(response)


class Block:
    def __init__(self, type_, **kwargs):
        self.type = type_
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_generate_translates_messages_tools_and_response():
    response = type("R", (), {"content": [
        Block("text", text="我来查看文件"),
        Block("tool_use", id="toolu_1", name="read_file", input={"path": "calc.py"}),
    ]})()

    client = FakeClient(response)
    provider = ClaudeProvider(client, "claude-compatible")

    messages = [
        Message(role=ROLE_SYSTEM, content="system prompt"),
        Message(role=ROLE_USER, content="读取 calc.py"),
        Message(
            role=ROLE_USER,
            content="成功写入",
            tool_call_id="toolu_0",
        ),
    ]
    tools = [
        ToolDefinition(
            name="read_file",
            description="读取文件",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
    ]

    result = provider.generate(messages, tools)

    params = client.messages.params
    assert params["system"] == "system prompt"
    # system 不进 messages
    assert params["messages"][0]["role"] == "user"
    # 工具结果包装成 tool_result block
    assert params["messages"][1]["content"][0]["type"] == "tool_result"
    assert params["messages"][1]["content"][0]["tool_use_id"] == "toolu_0"
    # 工具定义的 properties / required 被拆出来
    assert params["tools"][0]["input_schema"]["required"] == ["path"]

    assert result.role == ROLE_ASSISTANT
    assert result.content == "我来查看文件"
    assert result.tool_calls == [
        ToolCall(id="toolu_1", name="read_file", arguments=json.dumps({"path": "calc.py"}, ensure_ascii=False))
    ]


def test_zhipu_claude_provider_requires_api_key(monkeypatch):
    from internal.provider.claude import new_zhipu_claude_provider

    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ZHIPU_API_KEY"):
        new_zhipu_claude_provider("claude-compatible")
