# cmd/claw/main.py
# 对应 Go 版: cmd/claw/main.go
# 第 3 章：接入 DeepSeek Provider，并通过天气 Mock 工具验证 Agent 主循环。
import logging
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from internal.engine.loop import AgentEngine
from internal.provider.openai import new_deepseek_provider
from internal.schema.message import ToolCall, ToolDefinition, ToolResult
from internal.tools.registry import Registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%Y/%m/%d %H:%M:%S",
)
log = logging.getLogger(__name__)


class MockRegistry(Registry):
    """用于实验的天气工具注册中心。"""

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


def main() -> None:
    if not os.getenv("DEEPSEEK_API_KEY"):
        sys.exit("请先配置 DEEPSEEK_API_KEY 环境变量")

    llm_provider = new_deepseek_provider("deepseek-chat")
    registry = MockRegistry()
    work_dir = os.getcwd()
    prompt = "我想去北京跑步，帮我查查天气适合吗？"

    # 将最后一个参数改为 False，即可运行关闭慢思考的对照组。
    eng = AgentEngine(llm_provider, registry, work_dir, True)
    eng.run(prompt)


if __name__ == "__main__":
    main()
