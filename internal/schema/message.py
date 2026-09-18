# internal/schema/message.py
# 对应 Go 版: internal/schema/message.go
# 定义引擎内部流转的统⼀消息格式（与具体模型⼚商解耦）。
from dataclasses import dataclass, field
# Go 版中的 type Role string + 常量定义。
# Python ⾥直接⽤字符串常量表达⻆⾊。
ROLE_SYSTEM = "system"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
@dataclass
class ToolCall:
 """模型发起的⼀次⼯具调⽤请求。arguments 保持为原始 JSON 字符串（对应 Go 的
json.RawMessage），
由各⼯具⾃⾏解析。"""
 id: str = ""
 name: str = ""
 arguments: str = ""
@dataclass
class Message:
 """⼀条上下⽂消息。tool_calls 仅在 assistant 消息中出现；tool_call_id 仅在承载⼯具执⾏结果
的
user 消息中出现。"""
 role: str = ""
 content: str = ""
 tool_calls: list[ToolCall] = field(default_factory=list)
 tool_call_id: str = ""
@dataclass
class ToolResult:
 """⼀次⼯具执⾏的结果。"""
 tool_call_id: str = ""
 output: str = ""
 is_error: bool = False
@dataclass
class ToolDefinition:
 """暴露给模型的⼯具定义（名称 + 描述 + JSON Schema ⼊参约束）。"""
 name: str = ""
 description: str = ""
 input_schema: dict | None = None