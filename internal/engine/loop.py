# internal/engine/loop.py
# 对应 Go 版: internal/engine/loop.go
# 第 2 章：Agent 的⼼脏 —— Reason(推理) -> Act(⾏动) -> Observe(观察) 主循环。
import logging
from internal.provider.interface import LLMProvider
from internal.schema.message import Message, ROLE_SYSTEM, ROLE_USER
from internal.tools.registry import Registry
log = logging.getLogger(__name__)
class AgentEngine:
 """Agent 引擎：持有 Provider(⼤脑) 与 Registry(⼿脚)，并锁定⼀个⼯作区⽬录。"""
 def __init__(self, provider: LLMProvider, registry: Registry, work_dir: str):
 self.provider = provider
 self.registry = registry
 self.work_dir = work_dir
 def run(self, user_prompt: str) -> None:
 log.info("[Engine] 引擎启动，锁定⼯作区: %s", self.work_dir)
 # 初始上下⽂：System Prompt(⼈设) + ⽤户任务
 context_history: list[Message] = [Message(role=ROLE_SYSTEM,content="You are
py-tiny-claw, an expert coding assistant. You have full
access to tools in the workspace.",),Message(role=ROLE_USER,content=user_prompt,),]
 turn_count = 0
 while True:
 turn_count += 1
 log.info("========== [Turn %d] 开始 ==========", turn_count)
 available_tools = self.registry.get_available_tools()
 # 1. Reason: 把完整上下⽂交给模型，等待它的下⼀步决策
 log.info("[Engine] 正在思考 (Reasoning)...")
 try:
 response_msg = self.provider.generate(context_history,
available_tools)
 except Exception as e:
 raise RuntimeError(f"模型⽣成失败: {e}") from e
 context_history.append(response_msg)
 if response_msg.content != "":
 print(f"🤖 模型: {response_msg.content}")
 # 2. 终⽌条件：模型不再请求⼯具调⽤，说明任务完成
 if len(response_msg.tool_calls) == 0:
 log.info("[Engine] 任务完成，退出循环。")
 break
 log.info("[Engine] 模型请求调⽤ %d 个⼯具...", len(response_msg.tool_calls))
 # 3. Act + Observe: 逐个执⾏⼯具，把结果作为观察写回上下⽂
 for tool_call in response_msg.tool_calls:
 log.info(" -> 🛠 执⾏⼯具: %s, 参数: %s", tool_call.name,
tool_call.argum
ents)
 result = self.registry.execute(tool_call)
 if result.is_error:
 log.info(" -> ❌ ⼯具执⾏报错: %s", result.output)
 else:
 log.info(" -> ✅ ⼯具执⾏成功 (返回 %d 字节)", len(result.output))
 observation_msg =
Message(role=ROLE_USER,content=result.output,tool_call_id=tool_call.id,)
 context_history.append(observation_msg)