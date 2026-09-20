# internal/engine/loop.py
# 对应 Go 版: internal/engine/loop.go
# 第 3 章：引入“慢思考”(Thinking Phase)：先剥夺工具强制模型规划，再放开工具让它行动。
import logging

from internal.provider.interface import LLMProvider
from internal.schema.message import Message, ROLE_ASSISTANT, ROLE_SYSTEM, ROLE_USER
from internal.tools.registry import Registry

log = logging.getLogger(__name__)


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
            log.info("[Engine] 模型请求调⽤ %d 个⼯具...", len(response_msg.tool_calls))

            # Act + Observe: 逐个执行工具，把结果作为观察写回上下文。
            for tool_call in response_msg.tool_calls:
                log.info(
                    " -> 🛠 执⾏⼯具: %s, 参数: %s",
                    tool_call.name,
                    tool_call.arguments,
                )
                result = self.registry.execute(tool_call)
                if result.is_error:
                    log.info(" -> ❌ ⼯具执⾏报错: %s", result.output)
                else:
                    log.info(" -> ✅ ⼯具执⾏成功 (返回 %d 字节)", len(result.output))
                observation_msg = Message(
                    role=ROLE_USER,
                    content=result.output,
                    tool_call_id=tool_call.id,
                )
                context_history.append(observation_msg)
