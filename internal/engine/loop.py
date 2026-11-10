# internal/engine/loop.py
# 对应 Go 版: internal/engine/loop.go
# 第 3 章：引入“慢思考”(Thinking Phase)：先剥夺工具强制模型规划，再放开工具让它行动。
# 第 8 章：并发提效 Fork-Join。Go 版用 goroutine + WaitGroup，
# Python 版用 ThreadPoolExecutor 实现“并发执行、按序聚合”。
# 本课程改进：Fork 之前先判断——只读并发、涉写串行。
import logging
from concurrent.futures import ThreadPoolExecutor

from internal.provider.interface import LLMProvider
from internal.schema.message import (
    Message,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_USER,
    ToolCall,
)
from internal.tools.registry import Registry

log = logging.getLogger(__name__)

# 只读工具白名单：只有名单里的工具才允许并发执行。
# write_file / edit_file / bash 都可能修改文件系统状态，一律按“写”处理，串行执行。
READ_ONLY_TOOLS = {"read_file"}

# 单次任务的最大轮数熔断：防止模型陷入"失败→重试"死循环无限烧 token
MAX_TURNS = 25


class AgentEngine:
    """Agent 引擎：持有 Provider(⼤脑) 与 Registry(⼿脚)，并锁定⼀个⼯作区⽬录。"""

    def __init__(
        self,
        provider: LLMProvider,
        registry: Registry,
        work_dir: str,
        enable_thinking: bool,
    ):
        self.provider = provider
        self.registry = registry
        self.work_dir = work_dir
        self.enable_thinking = enable_thinking

    def run(self, user_prompt: str) -> None:
        log.info("[Engine] 引擎启动，锁定⼯作区: %s", self.work_dir)
        log.info("[Engine] 慢思考模式 (Thinking Phase): %s", self.enable_thinking)
        # 初始上下⽂：System Prompt(⼈设) + ⽤户任务
        context_history: list[Message] = [
            Message(
                role=ROLE_SYSTEM,
                content=(
                    "You are py-tiny-claw, an expert coding assistant. "
                    "You have full access to tools in the workspace."
                ),
            ),
            Message(role=ROLE_USER, content=user_prompt),
        ]
        turn_count = 0
        while True:
            if turn_count >= MAX_TURNS:
                raise RuntimeError(
                    f"任务在 {MAX_TURNS} 轮内未完成，已强制终止（防止死循环烧 token）"
                )
            turn_count += 1
            log.info("========== [Turn %d] 开始 ==========", turn_count)
            available_tools = self.registry.get_available_tools()

            # Phase 1: 不提供工具，让模型先形成计划。
            if self.enable_thinking:
                log.info(
                    "[Engine][Phase 1] 剥夺工具访问权，强制进入慢思考与规划阶段..."
                )
                try:
                    thinking_msg = self.provider.generate(context_history, None)
                except Exception as e:
                    raise RuntimeError(f"模型慢思考阶段生成失败: {e}") from e

                if thinking_msg.content:
                    log.info("  [内部思考 Trace]:\n%s", thinking_msg.content)
                    # Thinking 只保留文本计划，不把伪工具调用写入上下文。
                    context_history.append(
                        Message(role=ROLE_ASSISTANT, content=thinking_msg.content)
                    )

            # Phase 2: 恢复工具，让模型根据计划采取行动。
            log.info("[Engine][Phase 2] 恢复工具挂载，等待模型采取行动...")
            try:
                response_msg = self.provider.generate(context_history, available_tools)
            except Exception as e:
                raise RuntimeError(f"模型生成失败: {e}") from e
            context_history.append(response_msg)
            if response_msg.content != "":
                print(f"  [对外回复]: {response_msg.content}")

            # 终⽌条件：模型不再请求工调用，说明任务完成
            if len(response_msg.tool_calls) == 0:
                log.info("[Engine] 模型未请求调用工具，任务宣告完成。")
                break
            tool_calls = response_msg.tool_calls
            log.info("[Engine] 模型请求调⽤ %d 个⼯具...", len(tool_calls))

            # ① 判断本批次能否并发：数量多于 1 个，且全部命中只读白名单。
            #    只要有一个涉及写，整批降级为串行——宁可慢，不可错。
            can_parallel = len(tool_calls) > 1 and all(
                call.name in READ_ONLY_TOOLS for call in tool_calls
            )

            # ② 预分配结果列表：第 idx 个工具的结果固定放进第 idx 格。
            #    每个线程只写自己那一格，天然无竞争、无需加锁，顺序也永远不乱。
            observation_msgs: list[Message | None] = [None] * len(tool_calls)

            def run_tool(idx: int, call: ToolCall) -> None:
                """工作线程体：执行一个工具调用，并把观察写进自己的格子。"""
                log.info(
                    " -> [Worker-%d] 🛠 执⾏⼯具: %s, 参数: %s",
                    idx,
                    call.name,
                    call.arguments,
                )
                result = self.registry.execute(call)
                if result.is_error:
                    log.info(" -> [Worker-%d] ❌ ⼯具执⾏报错: %s", idx, result.output)
                else:
                    log.info(
                        " -> [Worker-%d] ✅ ⼯具执⾏成功 (返回 %d 字节)",
                        idx,
                        len(result.output),
                    )
                observation_msgs[idx] = Message(
                    role=ROLE_USER,
                    content=result.output,
                    tool_call_id=call.id,
                )

            # ③ 只读批次 → Fork-Join 并发；涉写批次 → 按模型给出的顺序串行。
            if can_parallel:
                log.info(
                    "[Engine] ⚡ 本批次 %d 个工具全部只读，Fork 并发执行...", len(tool_calls)
                )
                with ThreadPoolExecutor(max_workers=len(tool_calls)) as executor:
                    # Fork：把每个工具调用分派给一个线程
                    futures = [
                        executor.submit(run_tool, i, call)
                        for i, call in enumerate(tool_calls)
                    ]
                    # Join：逐个等待；线程内的异常会在此处重新抛出，不会静默丢失
                    for f in futures:
                        f.result()
                log.info("[Engine] 并发批次全部完成 (Join)，开始聚合观察结果...")
            else:
                log.info("[Engine] 🔒 本批次涉写或仅 1 个工具，串行执行以保证安全...")
                for i, call in enumerate(tool_calls):
                    run_tool(i, call)

            # ④ 按模型给出的原始顺序，把观察结果依次追加回上下文。
            #    并发只影响执行次序，不影响上下文次序。
            for obs in observation_msgs:
                context_history.append(obs)
