"""端到端集成测试：AgentEngine + 真实 Registry + 四大原语工具。

用「剧本化」的假 Provider 代替大模型，验证整条工具调用链路：
    Reason -> ToolCall -> Registry 分发 -> 工具执行 -> Observe 写回上下文
全程不联网、不消耗 token。
"""
import os
from pathlib import Path

import pytest

from internal.engine.loop import AgentEngine
from internal.schema.message import Message, ROLE_ASSISTANT, ROLE_USER, ToolCall
from internal.tools.bash import BashTool
from internal.tools.edit_file import EditFileTool
from internal.tools.read_file import ReadFileTool
from internal.tools.registry import new_registry
from internal.tools.write_file import WriteFileTool


class ScriptedProvider:
    """按预设剧本依次返回响应，并记录每次调用时的上下文。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def generate(self, messages, available_tools):
        self.calls.append((list(messages), available_tools))
        return self._responses[len(self.calls) - 1]


def tool_call(call_id: str, name: str, arguments: str) -> Message:
    return Message(
        role=ROLE_ASSISTANT,
        content="",
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
    )


@pytest.fixture()
def work_dir(tmp_path):
    return str(tmp_path)


def test_engine_full_tool_chain(work_dir):
    registry = new_registry()
    registry.register(ReadFileTool(work_dir))
    registry.register(WriteFileTool(work_dir))
    registry.register(BashTool(work_dir))
    registry.register(EditFileTool(work_dir))

    calc_source = "def add(a, b):\n    return a + b\n\n\nprint(add(2, 3))\n"

    provider = ScriptedProvider([
        # Turn 1: 写文件
        tool_call("c1", "write_file", '{"path": "calc.py", "content": %s}' % _json_str(calc_source)),
        # Turn 2: 执行
        tool_call("c2", "bash", '{"command": "python3 calc.py"}'),
        # Turn 3: 局部替换
        tool_call("c3", "edit_file", '{"path": "calc.py", "old_text": "return a + b", "new_text": "return a * b"}'),
        # Turn 4: 读回确认
        tool_call("c4", "read_file", '{"path": "calc.py"}'),
        # Turn 5: 再次执行
        tool_call("c5", "bash", '{"command": "python3 calc.py"}'),
        # Turn 6: 收尾，不再调用工具
        Message(role=ROLE_ASSISTANT, content="两次输出分别是 5 和 6。"),
    ])

    engine = AgentEngine(provider, registry, work_dir, False)
    engine.run("请依次使用四大原语完成任务")

    # 6 轮对话，第 6 轮没有工具调用即结束
    assert len(provider.calls) == 6
    # 每次调用都挂载了 4 个工具
    assert [t.name for t in provider.calls[0][1]] == [
        "read_file", "write_file", "bash", "edit_file",
    ]

    # 文件被真实创建，且替换生效
    after = Path(work_dir, "calc.py").read_text(encoding="utf-8")
    assert "return a * b" in after
    assert "return a + b" not in after

    # 工具结果以 observation 形式写回了上下文（最后一条是 bash 的输出）
    final_context = provider.calls[-1][0]
    observations = [m.content for m in final_context if m.role == ROLE_USER and m.tool_call_id]
    assert len(observations) == 5
    assert observations[0].startswith("成功将内容写入到文件")
    assert observations[1].strip() == "5"
    assert observations[-1].strip() == "6"


def _json_str(text: str) -> str:
    import json

    return json.dumps(text, ensure_ascii=False)
