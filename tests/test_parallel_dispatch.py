"""第 8 章：Fork-Join 并发分发的单元测试。

全部用「剧本化」的假 Provider 驱动 AgentEngine，不联网、不消耗 token。
核心验证四点：
    1. 只读批次真的并发（总耗时 ≈ 单次耗时，而非累加）
    2. 涉写批次退回串行（先写后读的因果顺序不被破坏）
    3. 无论并发还是串行，观察结果都按模型给出的原始顺序写回上下文
    4. 单个工具抛异常时被 Registry 兜住，不会让引擎崩溃
"""
import threading
import time

import pytest

from internal.engine.loop import READ_ONLY_TOOLS, AgentEngine
from internal.provider.interface import LLMProvider
from internal.schema.message import ROLE_ASSISTANT, ROLE_USER, Message, ToolCall
from internal.tools.read_file import ReadFileTool
from internal.tools.registry import BaseTool, new_registry
from internal.tools.write_file import WriteFileTool

# 模拟耗时用的基数。取 0.3 秒是为了让"并发"与"串行"的差距
# 既肉眼可辨（0.3s vs 0.9s），又不至于拖慢整个测试套件。
SLOW = 0.3


class ScriptedProvider(LLMProvider):
    """按剧本依次返回若干批工具调用，并记录每次看到的上下文。"""

    def __init__(self, batches):
        self._batches = list(batches)
        self.snapshots: list[list[Message]] = []
        self.outputs: dict[str, str] = {}

    def generate(self, messages, available_tools=None):
        self.snapshots.append(list(messages))
        for m in messages:
            if m.tool_call_id:
                self.outputs[m.tool_call_id] = m.content
        step = len(self.snapshots) - 1
        if step < len(self._batches):
            return Message(role=ROLE_ASSISTANT, tool_calls=self._batches[step])
        return Message(role=ROLE_ASSISTANT, content="任务完成。")

    @property
    def final_context(self) -> list[Message]:
        return self.snapshots[-1]

    def observation_ids(self) -> list[str]:
        """最终上下文里工具结果的排列顺序。"""
        return [m.tool_call_id for m in self.final_context if m.tool_call_id]

    def observations(self) -> list[Message]:
        return [m for m in self.final_context if m.role == ROLE_USER and m.tool_call_id]


class SlowReadFileTool(ReadFileTool):
    """模拟一次耗时 SLOW 秒的读取（比如读网络盘上的文件）。"""

    def execute(self, args: str) -> str:
        time.sleep(SLOW)
        return super().execute(args)


class ThreadRecordingTool(BaseTool):
    """记录自己是在哪个线程里被执行的，用来证明确实发生了并发。"""

    def __init__(self, work_dir: str, sink: list[str]):
        self.work_dir = work_dir
        self.sink = sink

    def name(self) -> str:
        return "read_file"

    def definition(self):
        return ReadFileTool(self.work_dir).definition()

    def execute(self, args: str) -> str:
        self.sink.append(threading.current_thread().name)
        time.sleep(SLOW)
        return ReadFileTool(self.work_dir).execute(args)


class BoomTool(BaseTool):
    """一个必定抛异常的工具，用来验证异常兜底。"""

    def name(self) -> str:
        return "read_file"

    def definition(self):
        return {
            "name": "read_file",
            "description": "故意爆炸的工具",
            "input_schema": {"type": "object", "properties": {}},
        }

    def execute(self, args: str) -> str:
        raise RuntimeError("工具内部炸了")


def call(cid: str, name: str, args: str) -> ToolCall:
    return ToolCall(id=cid, name=name, arguments=args)


def read(cid: str, filename: str) -> ToolCall:
    return call(cid, "read_file", '{"path": "%s"}' % filename)


@pytest.fixture()
def work_dir(tmp_path):
    for name, text in {"a.txt": "文件A", "b.txt": "文件B", "c.txt": "文件C"}.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return str(tmp_path)


def build_engine(provider, work_dir, slow=False):
    registry = new_registry()
    registry.register(SlowReadFileTool(work_dir) if slow else ReadFileTool(work_dir))
    registry.register(WriteFileTool(work_dir))
    return AgentEngine(provider, registry, work_dir, False)


# --------------------------------------------------------------------------
# 1. 白名单本身
# --------------------------------------------------------------------------

def test_read_only_whitelist_excludes_mutating_tools():
    """只读白名单里只能有 read_file，写类工具一律不在其中。"""
    assert READ_ONLY_TOOLS == {"read_file"}
    assert "write_file" not in READ_ONLY_TOOLS
    assert "edit_file" not in READ_ONLY_TOOLS
    assert "bash" not in READ_ONLY_TOOLS


# --------------------------------------------------------------------------
# 2. 只读批次 -> 并发
# --------------------------------------------------------------------------

def test_read_only_batch_runs_in_parallel(work_dir):
    """3 个读操作各自耗时 SLOW，并发后总耗时应接近 SLOW 而不是 3*SLOW。"""
    provider = ScriptedProvider([
        [read("r1", "a.txt"), read("r2", "b.txt"), read("r3", "c.txt")],
    ])
    engine = build_engine(provider, work_dir, slow=True)

    start = time.monotonic()
    engine.run("请一次性读取三个文件")
    cost = time.monotonic() - start

    assert cost < SLOW * 2, f"3 个读操作花了 {cost:.2f}s，说明没有并发起来"


def test_parallel_batch_uses_different_threads(work_dir):
    """并发批次里，每个工具调用应该跑在不同的工作线程上。"""
    sink: list[str] = []
    registry = new_registry()
    registry.register(ThreadRecordingTool(work_dir, sink))
    provider = ScriptedProvider([
        [read("r1", "a.txt"), read("r2", "b.txt"), read("r3", "c.txt")],
    ])

    AgentEngine(provider, registry, work_dir, False).run("并发读")

    assert len(sink) == 3
    assert len(set(sink)) == 3, f"三个调用跑在同一个线程里: {sink}"


def test_parallel_batch_keeps_model_order(work_dir):
    """并发只打乱执行先后，绝不能打乱上下文顺序。"""
    provider = ScriptedProvider([
        [read("r1", "a.txt"), read("r2", "b.txt"), read("r3", "c.txt")],
    ])
    engine = build_engine(provider, work_dir, slow=True)

    engine.run("并发读")

    assert provider.observation_ids() == ["r1", "r2", "r3"]


def test_observations_are_linked_to_their_own_call_id(work_dir):
    """每个观察消息的 tool_call_id 必须与它对应的调用一致（对号入座）。"""
    provider = ScriptedProvider([
        [read("r1", "a.txt"), read("r2", "b.txt"), read("r3", "c.txt")],
    ])
    engine = build_engine(provider, work_dir, slow=True)

    engine.run("并发读")

    assert provider.outputs["r1"] == "文件A"
    assert provider.outputs["r2"] == "文件B"
    assert provider.outputs["r3"] == "文件C"


# --------------------------------------------------------------------------
# 3. 涉写批次 -> 串行
# --------------------------------------------------------------------------

def test_write_batch_falls_back_to_serial(work_dir):
    """同一批里既有写又有读时，必须串行，保证"先写后读"成立。"""
    provider = ScriptedProvider([
        [
            call("w1", "write_file", '{"path": "d.txt", "content": "这是文件D"}'),
            read("r4", "a.txt"),
            read("r5", "d.txt"),
        ],
    ])
    engine = build_engine(provider, work_dir, slow=True)

    start = time.monotonic()
    engine.run("先写 d.txt 再读它")
    cost = time.monotonic() - start

    # 串行的耗时是 2 次慢读 + 1 次写的累加，一定明显大于并发阈值
    assert cost >= SLOW * 2, f"涉写批次只花了 {cost:.2f}s，疑似被错误地并发了"
    # 关键：读 d.txt 必须拿到刚刚写入的内容
    assert provider.outputs["r5"] == "这是文件D"


def test_serial_batch_keeps_model_order(work_dir):
    provider = ScriptedProvider([
        [
            call("w1", "write_file", '{"path": "d.txt", "content": "这是文件D"}'),
            read("r4", "a.txt"),
            read("r5", "d.txt"),
        ],
    ])
    engine = build_engine(provider, work_dir)

    engine.run("先写后读")

    assert provider.observation_ids() == ["w1", "r4", "r5"]


def test_single_tool_call_does_not_need_parallel(work_dir):
    """只有 1 个工具调用时不满足并发条件，走串行分支，结果照常写回。"""
    provider = ScriptedProvider([[read("r1", "a.txt")]])
    engine = build_engine(provider, work_dir, slow=True)

    engine.run("读一个文件")

    assert provider.outputs["r1"] == "文件A"
    assert provider.observation_ids() == ["r1"]


# --------------------------------------------------------------------------
# 4. 异常兜底
# --------------------------------------------------------------------------

def test_tool_exception_is_contained_not_crashing(work_dir):
    """并发批次里某个工具炸了，异常要被 Registry 兜住并转成错误观察。"""
    registry = new_registry()
    registry.register(BoomTool())
    registry.register(WriteFileTool(work_dir))
    provider = ScriptedProvider([
        [read("r1", "a.txt"), read("r2", "b.txt")],
    ])

    # 引擎不应崩溃
    AgentEngine(provider, registry, work_dir, False).run("读两个文件")

    obs = provider.observations()
    assert len(obs) == 2
    assert all("工具内部炸了" in m.content for m in obs)
    # 即便出错，顺序和 call_id 依然要对得上
    assert provider.observation_ids() == ["r1", "r2"]


def test_unknown_tool_name_is_reported_as_error(work_dir):
    """模型 hallucinate 出一个不存在的工具时，返回一个错误观察而不是崩溃。"""
    provider = ScriptedProvider([[call("x1", "no_such_tool", "{}")]])
    engine = build_engine(provider, work_dir)

    engine.run("调用一个不存在的工具")

    assert "no_such_tool" in provider.outputs["x1"]
