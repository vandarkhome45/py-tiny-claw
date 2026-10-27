## 一、实验摘要

本实验在 `py-tiny-claw` 的 Main Loop 与 DeepSeek API 之间增加统一的 Provider 层。

`OpenAIProvider` 负责将框架内部的 `Message`、`ToolDefinition` 转换为 OpenAI 兼容格式，
并把模型响应转换回内部 `Message` 与 `ToolCall`。`new_deepseek_provider()` 通过设置
`DEEPSEEK_API_KEY` 和 DeepSeek `base_url`，复用 OpenAI SDK 完成 DeepSeek 接入。

随后使用 `MockRegistry` 提供 `get_weather` 模拟天气工具，并保持模型、Prompt 和工具不变，
只切换 `EnableThinking`，观察两种模式的执行差异。

本次实验完成了以下内容：

1. 完成 `OpenAIProvider.generate()` 的双向消息转换。
2. 完成 `new_deepseek_provider()`。
3. 完成 `MockRegistry` 天气工具。
4. 完成 Thinking 两阶段控制逻辑。
5. 使用真实 DeepSeek API 分别运行 `EnableThinking=True` 和 `False`。
6. 8 个离线测试全部通过。

---

## 二、实验目的

1. 理解 Agent Harness 中 Provider 层的作用，明确 Provider 在 Main Loop 与模型 API
   之间承担的协议转换职责。
2. 掌握 `LLMProvider` 抽象接口的设计思路，并按照统一接口实现 `OpenAIProvider`。
3. 掌握 DeepSeek 对 OpenAI 兼容协议的复用方式。
4. 理解 `ToolDefinition`、`ToolCall`、`ToolResult` 在工具调用过程中的作用。
5. 通过控制变量实验，对比 `EnableThinking=True` 与 `False` 两种模式的运行过程和日志差异。

---

## 三、实验环境

| 项目 | 实际配置 |
|---|---|
| 操作系统 | macOS |
| Python | 3.14.6 |
| 依赖管理 | uv |
| OpenAI SDK | 3.16.2 |
| 模型 | `deepseek-chat` |
| API 地址 | `https://api.deepseek.com` |
| 环境变量 | `DEEPSEEK_API_KEY` |
| 测试框架 | pytest 9.1.1 |

环境准备命令：

```bash
cd /Users/gao_apple/py-tiny-claw/py-tiny-claw
uv sync
```

运行前确认 API Key 已配置，但不要把真实 Key 写入代码或提交到 Git：

```bash
if [[ -n "$DEEPSEEK_API_KEY" ]]; then
  echo "DEEPSEEK_API_KEY 已设置"
else
  echo "DEEPSEEK_API_KEY 未设置"
fi
```

---

## 四、实验原理

### 4.1 为什么需要 Provider 层

不同模型厂商的消息结构、工具定义和工具调用响应并不完全相同。如果 Main Loop 直接依赖
某个厂商 SDK，更换模型时就必须修改引擎内部代码。

加入 `LLMProvider` 后，职责被分成两部分：

| 组件 | 职责 |
|---|---|
| Main Loop | 维护上下文时间线，执行 Reason、Act、Observe 循环 |
| Provider | 请求格式转换、API 调用、响应格式转换 |

`OpenAIProvider` 对外继续提供统一的 `generate()` 接口，因此 Main Loop 不需要知道
DeepSeek、OpenAI 或其他兼容服务之间的协议细节。

### 4.2 消息转换关系

| 框架内部格式 | OpenAI 兼容请求格式 |
|---|---|
| `Message(role="system")` | `{"role": "system", "content": ...}` |
| 普通 `Message(role="user")` | `{"role": "user", "content": ...}` |
| 带 `tool_call_id` 的 `Message` | `{"role": "tool", "content": ..., "tool_call_id": ...}` |
| `Message(role="assistant")` | `{"role": "assistant", "content": ..., "tool_calls": ...}` |
| `ToolDefinition` | `{"type": "function", "function": {...}}` |

### 4.3 Thinking 两阶段

开启 Thinking 时，每一轮执行两个阶段：

```text
Phase 1：不提供工具
    ↓
模型生成内部计划与思考 Trace
    ↓
Phase 2：恢复工具
    ↓
模型决定是否调用工具
```

关闭 Thinking 时会跳过 Phase 1，直接执行 Phase 2。

---

## 五、项目结构

```text
py-tiny-claw/
├── cmd/
│   └── claw/
│       └── main.py
├── internal/
│   ├── engine/
│   │   └── loop.py
│   ├── provider/
│   │   ├── interface.py
│   │   └── openai.py
│   ├── schema/
│   │   └── message.py
│   └── tools/
│       └── registry.py
├── tests/
│   ├── test_engine.py
│   ├── test_main.py
│   └── test_openai_provider.py
└── pyproject.toml
```

---

## 六、代码实现

### 6.1 OpenAIProvider 完整代码

文件位置：`internal/provider/openai.py`

```python
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
```

### 6.2 new_deepseek_provider 完整代码

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

### 6.3 MockRegistry 完整代码

文件位置：`cmd/claw/main.py`

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

### 6.4 Thinking 控制代码

核心逻辑位于 `internal/engine/loop.py`：

```python
if self.enable_thinking:
    thinking_msg = self.provider.generate(context_history, None)
    if thinking_msg.content:
        log.info("  [内部思考 Trace]:\n%s", thinking_msg.content)
    context_history.append(
        Message(role=ROLE_ASSISTANT, content=thinking_msg.content)
    )

response_msg = self.provider.generate(context_history, available_tools)
```

---

## 七、控制变量实验

### 7.1 实验条件

两次实验保持以下条件完全一致，只修改 `EnableThinking`：

| 变量 | 测试 1 | 测试 2 |
|---|---|---|
| 模型 | `deepseek-chat` | `deepseek-chat` |
| Prompt | 我想去北京跑步，帮我查查天气适合吗？ | 我想去北京跑步，帮我查查天气适合吗？ |
| MockRegistry | `get_weather` | `get_weather` |
| EnableThinking | `True` | `False` |

### 7.2 EnableThinking=True 运行日志

运行日期：2026-09-22 10:14:25

```text
输入问题开始对话，输入 exit、quit 或按 Ctrl+C 退出。
你: 2026/09/22 10:14:25 [Engine] 引擎启动，锁定工作区: /Users/gao_apple/py-tiny-claw/py-tiny-claw
2026/09/22 10:14:25 [Engine] 慢思考模式 (Thinking Phase): True
2026/09/22 10:14:25 ========== [Turn 1] 开始 ==========
2026/09/22 10:14:25 [Engine][Phase 1] 剥夺工具访问权，强制进入慢思考与规划阶段...
2026/09/22 10:14:28 HTTP Request: POST https://api.deepseek.com/chat/completions "HTTP/1.1 200 OK"

2026/09/22 10:14:31   [内部思考 Trace]:
我很乐意帮你判断适不适合跑步，但我这边没有联网查询天气的能力，
也没法直接调用天气服务。不过我可以给你几个简单的办法，帮你快速
查到北京天气并做出判断……

2026/09/22 10:14:31 [Engine][Phase 2] 恢复工具挂载，等待模型采取行动...
2026/09/22 10:14:31 HTTP Request: POST https://api.deepseek.com/chat/completions "HTTP/1.1 200 OK"
2026/09/22 10:14:33 [Engine] 模型未请求调用工具，任务宣告完成。

  [对外回复]:
看起来你还没把天气信息发给我。要不你先把查到的北京天气数据贴过来
（温度、AQI、风力、降水），我立刻帮你分析适不适合跑步、穿什么、
注意啥。
```

本次运行现象：

1. Phase 1 生成了较长内部规划文本。
2. 模型在 Phase 1 中误判自身没有工具能力。
3. Phase 2 没有发出 `get_weather` 工具调用。
4. 总耗时约 8 秒，没有完成天气查询任务。

### 7.3 EnableThinking=False 运行日志

运行日期：2026-09-22 10:14:37

```text
2026/09/22 10:14:37 [Engine] 引擎启动，锁定工作区: /Users/gao_apple/py-tiny-claw/py-tiny-claw
2026/09/22 10:14:37 [Engine] 慢思考模式 (Thinking Phase): False
2026/09/22 10:14:37 ========== [Turn 1] 开始 ==========
2026/09/22 10:14:37 [Engine][Phase 2] 恢复工具挂载，等待模型采取行动...
2026/09/22 10:14:38 HTTP Request: POST https://api.deepseek.com/chat/completions "HTTP/1.1 200 OK"
2026/09/22 10:14:39 [Engine] 模型请求调用 1 个工具...
2026/09/22 10:14:39  -> 执行工具: get_weather, 参数: {"city": "北京"}
2026/09/22 10:14:39 -> [Mock 工具执行] 获取 get_weather 的天气中...
2026/09/22 10:14:39  -> 工具执行成功 (返回 21 字节)
2026/09/22 10:14:39 ========== [Turn 2] 开始 ==========
2026/09/22 10:14:39 [Engine][Phase 2] 恢复工具挂载，等待模型采取行动...
2026/09/22 10:14:40 HTTP Request: POST https://api.deepseek.com/chat/completions "HTTP/1.1 200 OK"
2026/09/22 10:14:41 [Engine] 模型未请求调用工具，任务宣告完成。

  [对外回复]:
北京的天气情况如下：

- 天气：晴天
- 气温：25 度

跑步适宜度评价：非常适合。25 度的晴天属于舒适的跑步天气。
建议避开正午、注意防晒并及时补水。
```

本次运行现象：

1. 跳过 Phase 1，直接进入 Phase 2。
2. 模型成功请求调用 `get_weather`。
3. `MockRegistry` 返回固定天气结果。
4. 模型根据工具结果生成了最终跑步建议。
5. 总耗时约 4 秒，工具调用链路完整。

### 7.4 两种模式对比

| 对比项 | EnableThinking=True | EnableThinking=False |
|---|---|---|
| 第一阶段 | 每轮先执行 Phase 1 | 跳过 Phase 1 |
| 工具访问 | Phase 1 无工具，Phase 2 恢复 | 全程提供工具 |
| 内部思考文本 | 较长 | 无独立 Phase 1 Trace |
| HTTP 请求次数 | 2 | 2 |
| 工具调用次数 | 0 | 1 |
| 本次结果 | 未查询天气，输出通用建议 | 成功调用天气工具并回答 |
| 本次耗时 | 约 8 秒 | 约 4 秒 |
| 适用场景 | 复杂推理、代码分析、重构 | 查天气、列文件等简单任务 |

补充说明：真实模型的输出具有一定随机性。本次 `True` 模式在 Phase 1 中误判“没有工具”，
并把这个判断带入后续上下文，导致 Phase 2 没有继续调用工具。这个现象也说明：
对于目标简单且工具路径明确的请求，额外慢思考不一定带来收益，反而可能增加延迟，
甚至干扰工具行动。

---

## 八、思考题

### 第 1 题：为什么需要 Provider 层？

如果 Main Loop 直接调用 DeepSeek SDK，引擎代码就会依赖 DeepSeek 的请求结构、
消息角色、工具定义格式和响应解析方式。更换为 OpenAI、Claude 或其他模型时，
Main Loop 必须同步修改，代码耦合度高，测试也更困难。

增加 Provider 层后：

1. Main Loop 只依赖统一的 `Message`、`ToolCall`、`ToolResult` 和 `ToolDefinition`。
2. 厂商差异被集中在 Provider 内部处理。
3. 更换模型时只需要增加或替换 Provider，不需要重写 Agent 主循环。
4. Provider 可以独立进行消息转换测试和模拟 API 测试。

因此，Provider 层的作用是把“Agent 如何运行”和“模型如何通信”这两个问题解耦。

### 第 2 题：两种 Thinking 模式如何选择？

开启 Thinking 后，每一轮都会先执行 Phase 1。模型在没有工具的情况下形成计划和推理文本，
然后进入 Phase 2，恢复工具并根据计划行动。

关闭 Thinking 后会跳过 Phase 1，直接提供工具并进入 Phase 2。

对于“查天气”这种任务：

1. 目标明确，所需工具和参数都清楚。
2. 决策路径短，不需要长篇规划。
3. 延迟和 Token 消耗比推理深度更重要。

因此 `EnableThinking=False` 更合适。复杂代码分析、依赖梳理、重构方案设计等任务，
可以考虑开启 Thinking，用更多算力换取更高的规划质量。

---

## 九、测试与验证

项目包含以下离线测试：

1. `OpenAIProvider` 的消息转换。
2. `ToolDefinition` 到 OpenAI tools 格式的转换。
3. API 响应到内部 `Message` 的转换。
4. `new_deepseek_provider()` 的环境变量与 `base_url` 配置。
5. Thinking 开启时的两阶段调用顺序。
6. Thinking 关闭时直接进入 Phase 2。
7. `MockRegistry` 的工具定义。
8. `MockRegistry.execute()` 的天气返回结果。

执行命令：

```bash
uv run pytest -q
```

执行结果：

```text
........                                                                 [100%]
8 passed in 0.22s
```

---

## 十、实验结论

本实验完成了 DeepSeek Provider 接入、内部消息与 OpenAI 兼容格式转换、
天气 Mock 工具接入和 Thinking 两阶段控制。

实验结果表明，Provider 层能够有效隔离模型 SDK 差异，使 Main Loop 保持稳定。
同时，`EnableThinking` 不是“越慢越好”的固定设置，而是一种算力分配策略：

1. 简单、明确、工具路径短的任务优先关闭 Thinking。
2. 复杂、需要规划和分解的任务可以开启 Thinking。
3. 是否开启应结合任务复杂度、响应时间、Token 成本和准确率共同判断。

这就是自适应推理的核心思想：根据任务需要动态分配计算资源。

---

## 十一、提交清单

- [x] `OpenAIProvider` 完整代码
- [x] `new_deepseek_provider()` 完整代码
- [x] `MockRegistry` 完整代码
- [x] `EnableThinking=True` 真实运行日志
- [x] `EnableThinking=False` 真实运行日志
- [x] 两种模式对比分析
- [x] 思考题
- [x] 自动化测试结果
