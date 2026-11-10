"""DSML 伪调用适配的单元测试。

DeepSeek 偶尔在 content 里泄漏内部 DSML 格式的伪调用：
    <｜｜DSML｜｜ invoke name="bash">
    <｜｜DSML｜｜ parameter name="command" string="true">ls -la</｜｜DSML｜｜ parameter>
    </｜｜DSML｜｜ invoke>

Provider 层的策略：慢思考阶段整体剥离（防上下文污染）；
行动阶段兜底解析成真正的 ToolCall（防调用被静默丢弃）。
"""
import json

from internal.provider.openai import OpenAIProvider, parse_dsml_tool_calls, strip_dsml
from internal.schema.message import Message, ROLE_ASSISTANT, ROLE_USER, ToolCall

SAMPLE = """我先规划一下。
<｜｜DSML｜｜ calls>
<｜｜DSML｜｜ invoke name="write_file">
<｜｜DSML｜｜ parameter name="path" string="true">summary.txt</｜｜DSML｜｜ parameter>
<｜｜DSML｜｜ parameter name="content" string="true">汇总结果</｜｜DSML｜｜ parameter>
</｜｜DSML｜｜ invoke>
</｜｜DSML｜｜ calls>
接下来执行。"""


def test_strip_dsml_removes_all_tags():
    clean = strip_dsml(SAMPLE)
    assert "｜｜DSML｜｜" not in clean
    assert "summary.txt" not in clean  # 整块 invoke 连同参数一起删掉
    assert "我先规划一下" in clean
    assert "接下来执行" in clean


def test_strip_dsml_keeps_plain_text_untouched():
    text = "普通文本，不含任何特殊标记。"
    assert strip_dsml(text) == text


def test_parse_dsml_extracts_tool_calls():
    clean, calls = parse_dsml_tool_calls(SAMPLE)

    assert "｜｜DSML｜｜" not in clean
    assert len(calls) == 1
    assert calls[0].name == "write_file"
    assert calls[0].id == "dsml_0"
    args = json.loads(calls[0].arguments)
    assert args["path"] == "summary.txt"
    assert args["content"] == "汇总结果"


def test_parse_dsml_handles_multiple_invokes():
    text = (
        '<｜｜DSML｜｜ invoke name="read_file">'
        '<｜｜DSML｜｜ parameter name="path" string="true">a.txt</｜｜DSML｜｜ parameter>'
        '</｜｜DSML｜｜ invoke>'
        '<｜｜DSML｜｜ invoke name="read_file">'
        '<｜｜DSML｜｜ parameter name="path" string="true">b.txt</｜｜DSML｜｜ parameter>'
        '</｜｜DSML｜｜ invoke>'
    )
    clean, calls = parse_dsml_tool_calls(text)

    assert len(calls) == 2
    assert {c.id for c in calls} == {"dsml_0", "dsml_1"}
    assert json.loads(calls[0].arguments)["path"] == "a.txt"
    assert json.loads(calls[1].arguments)["path"] == "b.txt"


# ---------------------------------------------------------------------
# Provider 层行为：generate 返回前的清洗 / 兜底解析
# ---------------------------------------------------------------------


class _FakeToolCall:
    def __init__(self, id, name, arguments):
        self.type = "function"
        self.id = id
        self.function = type(
            "F", (), {"name": name, "arguments": arguments}
        )()


class _FakeChoice:
    def __init__(self, content, tool_calls):
        self.message = type(
            "M", (), {"content": content, "tool_calls": tool_calls}
        )()


class _FakeResponse:
    def __init__(self, content, tool_calls=None):
        self.choices = [_FakeChoice(content, tool_calls)]


class _FakeCompletions:
    def __init__(self, response):
        self._response = response

    def create(self, **params):
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.chat = type("C", (), {"completions": _FakeCompletions(response)})()


def _make_provider(response) -> OpenAIProvider:
    return OpenAIProvider(client=_FakeClient(response), model="fake")


def test_generate_strips_dsml_when_no_tools_mounted():
    """慢思考阶段（tools=None）：伪调用必须被剥离，不进上下文。"""
    provider = _make_provider(_FakeResponse(SAMPLE))

    msg = provider.generate([Message(role=ROLE_USER, content="规划一下")], None)

    assert msg.role == ROLE_ASSISTANT
    assert "｜｜DSML｜｜" not in msg.content
    assert msg.tool_calls == []


def test_generate_parses_dsml_when_tools_mounted():
    """行动阶段：tool_calls 为空但 content 含 DSML 时，兜底解析成真调用。"""
    provider = _make_provider(_FakeResponse(SAMPLE))
    tools = [type("T", (), {"name": "write_file", "description": "", "input_schema": {}})()]

    msg = provider.generate([Message(role=ROLE_USER, content="写文件")], tools)

    assert "｜｜DSML｜｜" not in msg.content
    assert len(msg.tool_calls) == 1
    assert msg.tool_calls[0].name == "write_file"
    args = json.loads(msg.tool_calls[0].arguments)
    assert args["path"] == "summary.txt"


def test_generate_keeps_standard_tool_calls_untouched():
    """标准 tool_calls 正常时，DSML 兜底逻辑不应介入。"""
    std = _FakeToolCall("call_1", "bash", '{"command": "ls"}')
    provider = _make_provider(_FakeResponse("执行命令", [std]))
    tools = [type("T", (), {"name": "bash", "description": "", "input_schema": {}})()]

    msg = provider.generate([Message(role=ROLE_USER, content="列目录")], tools)

    assert msg.content == "执行命令"
    assert len(msg.tool_calls) == 1
    assert msg.tool_calls[0].id == "call_1"
    assert msg.tool_calls[0].name == "bash"
    assert msg.tool_calls[0].arguments == '{"command": "ls"}'
