# internal/provider/openai.py
# 对应 Go 版: internal/provider/openai.go
# 将框架内部消息格式与 OpenAI 兼容 API 格式互相转换。
# 第 3 章：接入 DeepSeek；第 6 章：补充异常兜底与智谱兼容端点。
# 期中大作业：适配 DeepSeek 的 DSML 伪调用泄漏问题（见模块底部函数）。
import json
import os
import re

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

        try:
            response = self.client.chat.completions.create(**params)
        except Exception as e:
            raise RuntimeError(f"OpenAI 兼容 API 请求失败: {e}") from e

        if not response.choices:
            raise RuntimeError("API 返回了空的 Choices")

        choice = response.choices[0].message
        content = choice.content or ""

        # 慢思考阶段（未挂载工具）：模型看不见工具，却偶尔会"脑补"出
        # <｜｜DSML｜｜ invoke ...> 伪调用文本。若原样写回上下文，后续轮次
        # 模型会模仿这种格式，把真正的工具调用也写成 DSML 文本而不是走
        # 标准 tool_calls 字段，导致调用被静默丢弃。因此在协议边界清洗。
        if available_tools is None:
            return Message(role=ROLE_ASSISTANT, content=strip_dsml(content))

        result_msg = Message(
            role=ROLE_ASSISTANT,
            content=content,
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

        # 行动阶段兜底：模型已挂载工具却仍把调用写成 DSML 文本
        # （tool_calls 字段为空）时，主动解析成真正的 ToolCall，
        # 不让 write_file 这类关键调用被静默丢弃。
        if not result_msg.tool_calls and _INVOKE_RE.search(content):
            clean_content, dsml_calls = parse_dsml_tool_calls(content)
            if dsml_calls:
                result_msg.content = clean_content
                result_msg.tool_calls.extend(dsml_calls)
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


# ======================= DeepSeek DSML 伪调用适配 =======================
# DeepSeek 部分版本会在 content 里泄漏内部 DSML 格式的伪调用，形如：
#   <｜｜DSML｜｜ calls>
#   <｜｜DSML｜｜ invoke name="bash">
#   <｜｜DSML｜｜ parameter name="command" string="true">ls -la</｜｜DSML｜｜ parameter>
#   </｜｜DSML｜｜ invoke>
#   </｜｜DSML｜｜ calls>
# 危害：① 写回上下文会"教坏"后续轮次；② 服务端把 invoke 强转 tool_calls 时
# arguments 边界切错，JSON 解析失败；③ 调用被完全留在 content 里则直接丢失。
# 处理策略：慢思考阶段整体剥离；行动阶段兜底解析成真正的 ToolCall。

# 任意 DSML 开/闭标签（｜为全角竖线 U+FF5C）
_TAG_RE = re.compile(r"</?｜｜DSML｜｜[^>]*>")
# 一个完整的 invoke 块：name + 若干 parameter
_INVOKE_RE = re.compile(
    r'<｜｜DSML｜｜ invoke name="(?P<name>[^"]*)"[^>]*>'
    r"(?P<body>.*?)</｜｜DSML｜｜ invoke\s*>",
    re.DOTALL,
)
# invoke 体内单个 parameter：name + 值
_PARAM_RE = re.compile(
    r'<｜｜DSML｜｜ parameter name="(?P<pname>[^"]*)"[^>]*>'
    r"(?P<pval>.*?)</｜｜DSML｜｜ parameter\s*>",
    re.DOTALL,
)


def strip_dsml(text: str) -> str:
    """剥离文本中的全部 DSML 痕迹：先删整块 invoke，再扫残留标签。"""
    if not text or "｜｜DSML｜｜" not in text:
        return text
    text = _INVOKE_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    return text.strip()


def parse_dsml_tool_calls(content: str) -> tuple[str, list[ToolCall]]:
    """把 content 里的 DSML 伪调用解析成真正的 ToolCall 列表。

    返回 (清洗后的纯文本, 调用列表)。参数按 name -> value 收集，
    重新序列化为合法 JSON，绕开服务端切割错位产生的脏 arguments。
    """
    calls: list[ToolCall] = []
    for match in _INVOKE_RE.finditer(content):
        name = match.group("name")
        if not name:
            continue
        params: dict[str, str] = {}
        for pm in _PARAM_RE.finditer(match.group("body")):
            params[pm.group("pname")] = pm.group("pval").strip()
        calls.append(
            ToolCall(
                id=f"dsml_{len(calls)}",
                name=name,
                arguments=json.dumps(params, ensure_ascii=False),
            )
        )
    clean = strip_dsml(content)
    return clean, calls


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


def new_zhipu_openai_provider(model: str) -> OpenAIProvider:
    """对应 Go 版的 NewZhipuOpenAIProvider 构造函数（第 6 章新增）。"""
    api_key = os.getenv("ZHIPU_API_KEY")
    if not api_key:
        raise RuntimeError("请设置 ZHIPU_API_KEY 环境变量")

    return OpenAIProvider(
        client=openai.OpenAI(
            api_key=api_key,
            base_url="https://open.bigmodel.cn/api/paas/v4/",
        ),
        model=model,
    )
