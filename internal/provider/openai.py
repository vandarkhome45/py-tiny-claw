# internal/provider/openai.py
# 对应 Go 版: internal/provider/openai.go
# 将框架内部消息格式与 OpenAI 兼容 API 格式互相转换。
import os

import openai

from internal.provider.interface import LLMProvider
from internal.schema.message import (
    Message,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_USER,
    ToolCall,
    ToolDefinition,
)


class OpenAIProvider(LLMProvider):
    """基于 OpenAI Chat Completions 协议的 Provider。"""

    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def generate(
        self,
        msgs: list[Message],
        available_tools: list[ToolDefinition] | None = None,
    ) -> Message:
        openai_msgs = self._convert_messages(msgs)
        openai_tools = self._convert_tools(available_tools)

        params = {
            "model": self.model,
            "messages": openai_msgs,
        }
        if openai_tools:
            params["tools"] = openai_tools

        response = self.client.chat.completions.create(**params)
        choice = response.choices[0].message

        result_msg = Message(
            role=ROLE_ASSISTANT,
            content=choice.content or "",
        )
        for tool_call in choice.tool_calls or []:
            if tool_call.type != "function":
                continue
            result_msg.tool_calls.append(
                ToolCall(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    arguments=tool_call.function.arguments,
                )
            )
        return result_msg

    @staticmethod
    def _convert_messages(msgs: list[Message]) -> list[dict]:
        openai_msgs = []
        for msg in msgs:
            if msg.role == ROLE_SYSTEM:
                openai_msgs.append(
                    {"role": ROLE_SYSTEM, "content": msg.content}
                )
            elif msg.role == ROLE_USER:
                if msg.tool_call_id:
                    openai_msgs.append(
                        {
                            "role": "tool",
                            "content": msg.content,
                            "tool_call_id": msg.tool_call_id,
                        }
                    )
                else:
                    openai_msgs.append({"role": ROLE_USER, "content": msg.content})
            elif msg.role == ROLE_ASSISTANT:
                assistant_msg = {"role": ROLE_ASSISTANT}
                if msg.content:
                    assistant_msg["content"] = msg.content
                if msg.tool_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.name,
                                "arguments": tool_call.arguments,
                            },
                        }
                        for tool_call in msg.tool_calls
                    ]
                openai_msgs.append(assistant_msg)
            else:
                raise ValueError(f"不支持的消息角色: {msg.role}")
        return openai_msgs

    @staticmethod
    def _convert_tools(
        available_tools: list[ToolDefinition] | None,
    ) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema or {},
                },
            }
            for tool in available_tools or []
        ]


def new_deepseek_provider(model: str) -> OpenAIProvider:
    """使用 OpenAI 兼容协议构造 DeepSeek Provider。"""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("请设置 DEEPSEEK_API_KEY 环境变量")

    return OpenAIProvider(
        client=openai.OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
        ),
        model=model,
    )
