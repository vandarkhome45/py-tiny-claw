# Python 基本语法实验报告

> **课程名称：** AI 智能体开发基础  
> **实验名称：** Provider 接入与自适应推理  
> **项目：** py-tiny-claw

## 一、实验目的

1. 理解 Agent Harness 中 Provider 层承担的协议转换职责。
2. 使用统一的 `LLMProvider` 接口接入 DeepSeek 的 OpenAI 兼容 API。
3. 完成内部 `Message`、`ToolDefinition`、`ToolCall` 与 OpenAI 数据格式之间的转换。
4. 使用 `MockRegistry` 模拟天气工具，验证完整的工具调用循环。
5. 通过控制 `EnableThinking`，对比慢思考模式与直接行动模式。

## 二、实验环境

- Python 3.10 及以上
- `openai` SDK
- 环境变量 `DEEPSEEK_API_KEY`
- 运行命令：`uv run python cmd/claw/main.py`

## 三、代码实现

### 1. OpenAIProvider

完整代码位于 `internal/provider/openai.py`：

```python
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
```

### 2. new_deepseek_provider

```python
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
```

### 3. MockRegistry

```python
class MockRegistry(Registry):
    """用于实验的天气工具注册中心。"""

    def get_available_tools(self) -> list[ToolDefinition]:
        return [
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

    def execute(self, call: ToolCall) -> ToolResult:
        log.info("-> [Mock 工具执行] 获取 %s 的天气中...", call.name)
        return ToolResult(
            tool_call_id=call.id,
            output="API 返回：今天是晴天，气温 25 度。",
            is_error=False,
        )
```

## 四、实验记录

### 测试 1：EnableThinking = True

将 `cmd/claw/main.py` 中引擎构造代码设置为：

```python
eng = AgentEngine(llm_provider, registry, work_dir, True)
```

真实运行日志：

```text
待配置 DEEPSEEK_API_KEY 后运行并粘贴真实日志。
```

### 测试 2：EnableThinking = False

将同一个参数改为：

```python
eng = AgentEngine(llm_provider, registry, work_dir, False)
```

真实运行日志：

```text
待配置 DEEPSEEK_API_KEY 后运行并粘贴真实日志。
```

以上两次运行保持 Prompt、模型和 `MockRegistry` 完全一致，仅修改
`EnableThinking`。

## 五、思考题

### 第 1 题

Provider 层把“维护消息时间线和执行 Agent 循环”的职责，与“调用某个模型厂商 SDK”的职责分开。
如果 Main Loop 直接调用 DeepSeek SDK，更换模型厂商时就要修改引擎代码，并处理不同厂商的消息和工具调用格式。
增加 `LLMProvider` 后，Main Loop 只依赖统一的 `Message`、`ToolCall` 和 `ToolDefinition`。
OpenAIProvider 负责请求和响应的双向翻译，因此替换模型时只需要增加或替换 Provider，而不需要修改主循环。

### 第 2 题

开启 Thinking 后，每一轮都会先执行 Phase 1，在不提供工具的情况下生成内部计划，然后进入 Phase 2，
恢复工具并让模型执行行动。关闭 Thinking 后会跳过 Phase 1，直接进入 Phase 2。

对于“查天气”这种目标明确、步骤简单的任务，关闭 Thinking 更合适。它减少了隐藏分析文本、
响应延迟和 Token 消耗，同时不影响工具调用与最终回答。复杂代码分析或重构类任务才更适合开启 Thinking。

## 六、验证结果

项目包含 Provider 转换、DeepSeek 工厂、Thinking 开关和 MockRegistry 的离线测试。
当前执行结果为：

```text
8 passed
```

真实 DeepSeek 日志需要设置有效的 `DEEPSEEK_API_KEY` 后生成。
