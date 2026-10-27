# test_parallel.py
# 第 8 章离线验证脚本：用"假模型"代替 DeepSeek，不消耗任何 token。
# 假模型按剧本依次返回 3 批工具调用，观察引擎是并发还是串行：
#   第 1 批：read a / read b / read c         -> 全只读，应并发（约 1 秒）
#   第 2 批：write d / read a / read d         -> 含写操作，应串行（约 2 秒）
#   第 3 批：bash "sleep 1 && cat d.txt"      -> 只有 1 个工具，直接执行
# 为了让效果肉眼可见，这里给 read_file 和 bash 都加了 1 秒的模拟耗时。
#
# 运行方式（在 py-tiny-claw 目录下）: python test_parallel.py
import logging
import sys
import tempfile
import time
from pathlib import Path

# 注意：本项目的 cmd/ 包会遮蔽 Python 标准库 cmd 模块，
# 因此工程根目录只能追加到 sys.path 末尾，绝不能插到最前面。
_project_root = str(Path(__file__).resolve().parent)
if _project_root not in sys.path:
    sys.path.append(_project_root)

from internal.engine.loop import AgentEngine
from internal.provider.interface import LLMProvider
from internal.schema.message import Message, ToolCall, ROLE_ASSISTANT
from internal.tools.bash import BashTool
from internal.tools.edit_file import EditFileTool
from internal.tools.read_file import ReadFileTool
from internal.tools.registry import new_registry
from internal.tools.write_file import WriteFileTool

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")


class SlowReadFileTool(ReadFileTool):
    """模拟一次耗时 1 秒的读取（比如读取网络上的文件）"""

    def execute(self, args: str) -> str:
        time.sleep(1)
        return super().execute(args)


def call(cid, name, args):
    return ToolCall(id=cid, name=name, arguments=args)


# 假模型的剧本：每次 generate 返回下一批工具调用
SCRIPT = [
    [call("r1", "read_file", '{"path": "a.txt"}'),
     call("r2", "read_file", '{"path": "b.txt"}'),
     call("r3", "read_file", '{"path": "c.txt"}')],
    [call("w1", "write_file",
          '{"path": "d.txt", "content": "这是文件D"}'),
     call("r4", "read_file", '{"path": "a.txt"}'),
     call("r5", "read_file", '{"path": "d.txt"}')],
    [call("b1", "bash", '{"command": "sleep 1 && cat d.txt"}')],
]


class FakeProvider(LLMProvider):
    def __init__(self):
        self.step = 0
        self.times = []        # 每次被调用的时刻，用来计算每批耗时
        self.snapshots = []    # 每次被调用时，上下文中的工具结果编号
        self.outputs = {}      # 工具结果编号 -> 结果内容

    def generate(self, messages, available_tools=None):
        self.times.append(time.monotonic())
        self.snapshots.append(
            [m.tool_call_id for m in messages if m.tool_call_id])
        for m in messages:
            if m.tool_call_id:
                self.outputs[m.tool_call_id] = m.content
        if self.step < len(SCRIPT):
            batch = SCRIPT[self.step]
            self.step += 1
            return Message(role=ROLE_ASSISTANT, tool_calls=batch)
        return Message(role=ROLE_ASSISTANT, content="任务完成。")


def main():
    with tempfile.TemporaryDirectory() as work_dir:
        for name, text in {"a.txt": "文件A", "b.txt": "文件B",
                           "c.txt": "文件C"}.items():
            Path(work_dir, name).write_text(text, encoding="utf-8")

        registry = new_registry()
        registry.register(SlowReadFileTool(work_dir))
        registry.register(WriteFileTool(work_dir))
        registry.register(BashTool(work_dir))
        registry.register(EditFileTool(work_dir))

        provider = FakeProvider()
        AgentEngine(provider, registry, work_dir, False).run("测试")

    t = provider.times
    cost = [t[i + 1] - t[i] for i in range(len(SCRIPT))]
    ids = provider.snapshots[-1]

    checks = [
        ("第 1 批 3 个只读工具并发，耗时约 1 秒", cost[0] < 1.6),
        ("第 2 批含写操作串行，耗时约 2 秒", cost[1] >= 1.9),
        ("串行保证先写后读：读 d.txt 拿到了刚写入的内容",
         provider.outputs.get("r5") == "这是文件D"),
        ("第 3 批单个 bash 正常执行", cost[2] >= 1.0),
        ("结果按模型给出的原始顺序写回上下文",
         ids == ["r1", "r2", "r3", "w1", "r4", "r5", "b1"]),
    ]

    print("\n========== 测试汇总 ==========")
    for i, c in enumerate(cost, 1):
        print(f"第 {i} 批耗时: {c:.2f} 秒")
    print(f"上下文中工具结果的顺序: {ids}")
    for title, ok in checks:
        print(f"{'✅ PASS' if ok else '❌ FAIL'}  {title}")


if __name__ == "__main__":
    main()
