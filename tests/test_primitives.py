"""四大原语工具的 pytest 版本，覆盖 test_tools.py 的 5 个离线用例。"""
import json

import pytest

from internal.schema.message import ToolCall
from internal.tools import bash as bash_module
from internal.tools.bash import BashTool
from internal.tools.edit_file import EditFileTool, fuzzy_replace
from internal.tools.read_file import ReadFileTool
from internal.tools.registry import new_registry
from internal.tools.write_file import WriteFileTool

SERVER_CODE = '''def main():
    # 启动服务器
    print("Server is starting on port 8080...")
    # TODO: 增加鉴权逻辑
    if True:
        print("No auth, everyone can access.")

if __name__ == "__main__":
    main()
'''


@pytest.fixture()
def work_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture()
def registry(work_dir):
    reg = new_registry()
    reg.register(ReadFileTool(work_dir))
    reg.register(WriteFileTool(work_dir))
    reg.register(BashTool(work_dir))
    reg.register(EditFileTool(work_dir))
    return reg


def call(name: str, **kwargs) -> ToolCall:
    return ToolCall(id=f"call_{name}", name=name, arguments=json.dumps(kwargs, ensure_ascii=False))


# --------------------------- 用例 1：未知工具 ---------------------------

def test_unknown_tool_is_error_but_does_not_crash(registry):
    result = registry.execute(ToolCall(id="call_1", name="delete_all", arguments="{}"))

    assert result.is_error is True
    assert "delete_all" in result.output
    assert result.tool_call_id == "call_1"


# --------------------------- 用例 2：参数非法 JSON ---------------------------

def test_invalid_json_arguments_are_swallowed(registry):
    result = registry.execute(
        ToolCall(id="call_2", name="read_file", arguments="{path: server.py")
    )

    assert result.is_error is True
    assert result.tool_call_id == "call_2"


# --------------------------- 用例 3：bash 自纠错回传 ---------------------------

def test_bash_nonzero_exit_is_returned_not_raised(registry):
    result = registry.execute(call("bash", command="echo 出错啦 && exit 3"))

    assert result.is_error is False
    assert "exit status 3" in result.output
    assert "出错啦" in result.output


def test_bash_empty_output_hint(registry):
    result = registry.execute(call("bash", command="true"))

    assert result.is_error is False
    assert result.output == "命令执行成功，无终端输出。"


def test_bash_output_truncation(registry):
    result = registry.execute(call("bash", command="python3 -c \"print('x'*9000)\""))

    assert result.is_error is False
    assert len(result.output) < 9000
    assert "已被系统截断" in result.output


def test_bash_timeout_is_reported(registry, monkeypatch):
    monkeypatch.setattr(bash_module, "TIMEOUT_SECONDS", 1)

    result = registry.execute(call("bash", command="sleep 5"))

    assert result.is_error is False
    assert "超时" in result.output


# --------------------------- 用例 4：edit_file 缩进陷阱 ---------------------------

def test_edit_file_indentation_trap_falls_back_to_line_match(registry, work_dir):
    import os

    with open(os.path.join(work_dir, "server.py"), "w", encoding="utf-8") as f:
        f.write(SERVER_CODE)

    old_text = '# TODO: 增加鉴权逻辑\nif True:\nprint("No auth, everyone can access.")'
    new_text = ('    # TODO: 增加鉴权逻辑\n'
                '    if user is None:\n'
                '        print("Forbidden!")\n'
                '        return')

    result = registry.execute(call("edit_file", path="server.py", old_text=old_text, new_text=new_text))

    assert result.is_error is False
    with open(os.path.join(work_dir, "server.py"), encoding="utf-8") as f:
        after = f.read()
    assert "if user is None:" in after
    assert "if True:" not in after


# --------------------------- 用例 5：唯一性安全底线 ---------------------------

def test_edit_file_ambiguous_match_is_rejected_and_file_untouched(registry, work_dir):
    import os

    original = "x = 1\nprint(x)\nx = 1\n"
    path = os.path.join(work_dir, "dup.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(original)

    result = registry.execute(
        call("edit_file", path="dup.py", old_text="x = 1", new_text="x = 2")
    )

    assert result.is_error is True
    with open(path, encoding="utf-8") as f:
        assert f.read() == original


# --------------------------- fuzzy_replace 分级链单测 ---------------------------

def test_fuzzy_level1_exact_match():
    assert fuzzy_replace("a = 1\n", "a = 1", "a = 2") == "a = 2\n"


def test_fuzzy_level2_crlf_normalization():
    assert fuzzy_replace("a\r\nb\r\n", "a\nb", "NEW") == "NEW\n"


def test_fuzzy_level3_strip_whitespace():
    assert fuzzy_replace("    foo()\n", "  foo()  ", "bar()") == "    bar()\n"


def test_fuzzy_not_found_raises():
    with pytest.raises(RuntimeError, match="未找到"):
        fuzzy_replace("abc\n", "zzz", "yyy")


# --------------------------- read_file / write_file ---------------------------

def test_write_then_read_roundtrip(registry, work_dir):
    import os

    assert registry.execute(call("write_file", path="hello.txt", content="你好")).is_error is False
    result = registry.execute(call("read_file", path="hello.txt"))

    assert result.is_error is False
    assert result.output == "你好"
    assert os.path.exists(os.path.join(work_dir, "hello.txt"))


def test_write_creates_parent_directory(registry, work_dir):
    import os

    registry.execute(call("write_file", path="a/b/c.txt", content="x"))

    assert os.path.exists(os.path.join(work_dir, "a", "b", "c.txt"))


def test_read_missing_file_is_error(registry):
    result = registry.execute(call("read_file", path="nope.txt"))

    assert result.is_error is True
    assert "打开文件失败" in result.output


def test_read_file_truncates_long_content(registry):
    long_text = "A" * 9000
    registry.execute(call("write_file", path="big.txt", content=long_text))

    result = registry.execute(call("read_file", path="big.txt"))

    assert result.is_error is False
    assert len(result.output) < 9000
    assert "已被系统截断" in result.output
