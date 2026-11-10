# cmd/claw/main.py
# 对应 Go 版: cmd/claw/main.go
# 第 3 章：接入 DeepSeek Provider，并通过天气 Mock 工具验证 Agent 主循环（REPL 入口）。
# 第 6 章：挂载 read_file / write_file / bash / edit_file 四大原语，
#         用一次综合任务验证 Tool Registry 的分发能力。
# 第 8 章：并发提效 Fork-Join（只读并发、涉写串行）。
# 期中大作业：默认入口为终端对话模式 TinyClaw——
#             助教在终端里说需求，智能体自己决定读哪些、写哪些、执行什么命令。
#
# 运行方式（在 py-tiny-claw 目录下）:
#   python -m cmd.claw.main             # 终端对话模式（大作业默认入口，慢思考默认开启）
#   python -m cmd.claw.main --no-thinking  # 同上，但关闭慢思考（对照组）
#   python -m cmd.claw.main --read      # 第 8 章：三个只读调用 -> 并发
#   python -m cmd.claw.main --mix       # 第 8 章：读写混合 -> 降级串行
#   python -m cmd.claw.main --tools     # 第 6 章：四大原语综合任务
#   python -m cmd.claw.main --repl      # 第 3 章：天气 Mock 工具 REPL（旧实验入口）
import argparse
import logging
import os
import sys
from pathlib import Path

if __package__ in (None, "") and str(Path(__file__).resolve().parents[2]) not in sys.path:
    # 直接以脚本方式运行（python cmd/claw/main.py 或 PyCharm Run）时补上项目根目录。
    # 必须判断是否已在 sys.path 中，避免重复插入导致本项目的 cmd/ 遮蔽标准库 cmd 模块。
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from internal.engine.loop import AgentEngine
from internal.provider.openai import new_deepseek_provider
from internal.schema.message import ToolCall, ToolDefinition, ToolResult
from internal.tools.bash import BashTool
from internal.tools.edit_file import EditFileTool
from internal.tools.read_file import ReadFileTool
from internal.tools.registry import RegistryImpl, new_registry
from internal.tools.write_file import WriteFileTool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%Y/%m/%d %H:%M:%S",
)
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 模型名。实验四课件用的是 deepseek-v4-flash，
# 这里沿用实验三中已实际跑通的 deepseek-chat；如需切换改这一处即可。
MODEL = "deepseek-chat"

# ============================ 第 8 章：并发演示 ============================

# 测试 1：三个互相独立的读操作 -> 应当并发（只读批次，Fork-Join）
PROMPT_READ = """
我当前目录下有 a.txt、b.txt、c.txt 三个文件。
为了节省时间，请你在同一轮中一次性调用工具读取这三个文件，
并将它们的内容综合起来告诉我。
"""

# 测试 2：同一轮里混入写操作 -> 应当退回串行（涉写批次，保证先写后读）
PROMPT_MIX = """
请在同一轮中同时完成两件事：
1. 用 write_file 创建 d.txt，内容为"这是文件D"
2. 用 read_file 读取 a.txt
完成后告诉我 a.txt 的内容。
"""

# ============================ 第 6 章：四大原语 ============================

TOOL_DEMO_PROMPT = """
请按顺序完成以下操作，每一步都使用对应的工具：
1. 用 write_file 创建 calc.py，内容是一个函数 add(a, b) 返回 a + b，并在文件末尾 print(add(2, 3))
2. 用 bash 执行 python calc.py
3. 用 edit_file 把 return a + b 改成 return a * b
4. 用 read_file 读取 calc.py 确认修改成功
5. 再用 bash 执行一次 python calc.py，告诉我两次输出分别是多少
"""


def prepare_files(work_dir: Path) -> None:
    """为第 8 章并发演示准备测试文件（等价于教材中的 3 条 echo 命令）。"""
    files = {
        "a.txt": "这是文件A，里面记录了前端的报错日志。",
        "b.txt": "这是文件B，里面记录了后端的接口响应时间。",
        "c.txt": "这是文件C，里面写着今天的日期是周五。",
    }
    for name, text in files.items():
        (work_dir / name).write_text(text + "\n", encoding="utf-8")


class MockRegistry(RegistryImpl):
    """第 3 章遗留的天气工具注册中心。

    继承 RegistryImpl 只是为了满足新版 Registry 的三方法契约；
    这里仍然只暴露一个固定的 get_weather 假工具。
    """

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


def build_tool_registry(work_dir: str):
    """把四大原语挂载到注册中心。"""
    registry = new_registry()
    registry.register(ReadFileTool(work_dir))
    registry.register(WriteFileTool(work_dir))
    registry.register(BashTool(work_dir))
    registry.register(EditFileTool(work_dir))
    return registry


def _require_api_key() -> None:
    """所有联网入口的统一前置校验。"""
    if not os.getenv("DEEPSEEK_API_KEY"):
        sys.exit("请先配置 DEEPSEEK_API_KEY 环境变量")


def _workspace_dir() -> str:
    """取得（必要时创建）被锁定的工作区目录 workspace/。"""
    work_dir = PROJECT_ROOT / "workspace"
    if not work_dir.exists():
        work_dir.mkdir(parents=True, exist_ok=True)
    return str(work_dir)


def run_parallel_demo(prompt: str, enable_thinking: bool = False) -> None:
    """第 8 章：并发提效演示入口。

    引擎会根据本批次的工具性质自行决定 Fork-Join 并发还是串行，
    这里只负责准备素材并把任务交给引擎。
    """
    _require_api_key()

    # 把 Agent 的活动范围锁定在 workspace/ 子目录，避免模型生成的文件弄乱项目代码
    work_dir_path = Path(_workspace_dir())
    prepare_files(work_dir_path)
    work_dir = str(work_dir_path)

    llm_provider = new_deepseek_provider(MODEL)
    registry = build_tool_registry(work_dir)

    # 默认关闭慢思考以节省 token；模型不肯一次发多个调用时可加 --thinking
    eng = AgentEngine(llm_provider, registry, work_dir, enable_thinking)

    try:
        eng.run(prompt)
    except Exception as e:
        sys.exit(f"引擎运行崩溃: {e}")


def run_tool_demo(enable_thinking: bool = False) -> None:
    """第 6 章：四大原语综合任务。"""
    _require_api_key()

    work_dir = _workspace_dir()

    llm_provider = new_deepseek_provider(MODEL)
    registry = build_tool_registry(work_dir)

    eng = AgentEngine(llm_provider, registry, work_dir, enable_thinking)

    try:
        eng.run(TOOL_DEMO_PROMPT)
    except Exception as e:
        sys.exit(f"引擎运行崩溃: {e}")


def run_repl() -> None:
    """第 3 章：交互式 REPL，用于观察 Thinking 两阶段的差异。"""
    _require_api_key()

    llm_provider = new_deepseek_provider(MODEL)
    registry = MockRegistry()
    work_dir = os.getcwd()

    # 将最后一个参数改为 False，即可运行关闭慢思考的对照组。
    eng = AgentEngine(llm_provider, registry, work_dir, True)
    print("输入问题开始对话，输入 exit、quit 或按 Ctrl+C 退出。")

    # 同 run_chat 的加固：防止 PyCharm 终端中文输入坏字节杀死进程
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass
    while True:
        try:
            prompt = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        except UnicodeDecodeError as e:
            print(f"⚠️ 输入编码异常，请重新输入: {e}")
            continue

        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit"}:
            break

        eng.run(prompt)


def run_chat(enable_thinking: bool = True) -> None:
    """期中大作业：TinyClaw 终端对话模式。

    每输入一句话运行一次智能体：模型先慢思考做规划，再按
    "思考 -> 行动 -> 观察" 循环调用四大原语工具，直到给出最终回答；
    回答完继续等待下一句，输入 exit 退出。
    """
    _require_api_key()

    # Agent 的活动范围锁定在 workspace/，工具的读写、bash 的 cwd 都出不去
    work_dir = _workspace_dir()

    llm_provider = new_deepseek_provider(MODEL)
    registry = build_tool_registry(work_dir)
    eng = AgentEngine(llm_provider, registry, work_dir, enable_thinking)

    print("💻 终端模式已启动，输入你的问题（输入 exit 退出）")
    print(f"   工作区: {work_dir}    模型: {MODEL}    慢思考: {'开' if enable_thinking else '关'}")
    # 加固：PyCharm 仿真终端的中文输入偶发产生坏字节，强制 UTF-8 并容错解码，
    # 避免 input() 抛 UnicodeDecodeError 直接杀死整个进程
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass
    while True:
        try:
            prompt = input("👤 你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        except UnicodeDecodeError as e:
            print(f"⚠️ 输入编码异常，请重新输入（PyCharm 终端中文输入偶发问题）: {e}")
            continue

        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit"}:
            print("👋 再见")
            break

        # 单轮任务的任何崩溃（网络、Provider 等）只结束本轮，对话不退出
        try:
            eng.run(prompt)
        except Exception as e:
            print(f"⚠️ 本轮任务出错: {e}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cmd.claw.main",
        description="TinyClaw 微型编程智能体（期中大作业：终端对话模式）",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--read",
        action="store_true",
        help="第 8 章：一次性读 3 个文件 -> 只读批次，并发执行",
    )
    group.add_argument(
        "--mix",
        action="store_true",
        help="第 8 章：同一轮里读写混合 -> 涉写批次，降级串行",
    )
    group.add_argument(
        "--tools",
        action="store_true",
        help="第 6 章：read/write/edit/bash 四大原语综合任务",
    )
    group.add_argument(
        "--repl",
        action="store_true",
        help="第 3 章：交互式 REPL（天气 Mock 工具 + 慢思考）",
    )
    parser.add_argument(
        "--no-thinking",
        dest="thinking",
        action="store_false",
        help="关闭慢思考模式（终端对话模式默认开启，此参数用于对照实验）",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()

    if args.repl:
        run_repl()
    elif args.mix:
        run_parallel_demo(PROMPT_MIX, args.thinking)
    elif args.tools:
        run_tool_demo(args.thinking)
    elif args.read:
        run_parallel_demo(PROMPT_READ, args.thinking)
    else:
        # 默认（大作业要求）：终端对话模式，慢思考开启
        run_chat(enable_thinking=args.thinking)


if __name__ == "__main__":
    main()
