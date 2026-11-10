# py-tiny-claw

一个用 Python 实现的**微型编程智能体（Agent Harness）**：在终端里说出需求，智能体自己规划、读写文件、执行命令，直到完成任务。

核心代码约 300 行，纯教学用途——目标是让「Agent 到底是怎么跑起来的」这件事可以被逐行读懂。

> 本项目是课程提供的 Go 版 tiny-claw 的 Python 移植与教学改造，配套《AI 智能体开发基础》第 3、6、8 讲实验。

---

## 它能做什么

```
👤 你: 帮我写一个 calc.py 实现加法，运行验证，然后改成乘法再运行一次
🤖 慢思考 → 规划步骤
🛠 write_file  → 创建 calc.py
🛠 bash        → python calc.py            # 输出 5
🛠 edit_file   → add 改成乘法
🛠 read_file   → 确认修改
🛠 bash        → python calc.py            # 输出 6
💬 两次输出分别是 5 和 6
```

模型调用的是 **DeepSeek 官方 API**（`deepseek-chat`），不是本地模型；不配 Key 或断网会直接报错，不做离线兜底。

---

## 快速开始

### 环境要求

- Python ≥ 3.10（开发环境为 3.14）
- [uv](https://docs.astral.sh/uv/) 或 pip
- 一个 DeepSeek API Key

### 安装

```bash
git clone https://github.com/vandarkhome45/py-tiny-claw.git
cd py-tiny-claw
uv sync                                 # 或 pip install -e .
export DEEPSEEK_API_KEY=sk-xxxxxxxx     # 建议写进 ~/.zshrc
```

### 运行

所有命令在项目根目录执行：

```bash
python -m cmd.claw.main                  # 终端对话模式（默认入口，慢思考开启）
python -m cmd.claw.main --no-thinking    # 关闭慢思考的对照组
python -m cmd.claw.main --read           # 第 8 讲：3 个只读工具 → 并发执行
python -m cmd.claw.main --mix            # 第 8 讲：读写混合 → 降级串行
python -m cmd.claw.main --tools          # 第 6 章：四大原语综合任务
python -m cmd.claw.main --repl           # 第 3 章：天气 Mock 工具 REPL
```

对话模式支持多轮：输入 `exit` / `quit` 退出；单轮任务出错只结束本轮，不会退出程序。

### 测试

```bash
uv run pytest                # 49 个用例
python test_tools.py         # 离线验证：四大原语（不联网）
python test_parallel.py      # 离线验证：Fork-Join 并发（不联网）
```

---

## 架构

```
cmd/claw/main.py            入口：CLI 参数、五种运行模式、工具装配
internal/
  engine/loop.py            Agent 主循环：慢思考 → 行动 → 观察 → 循环
  provider/interface.py     LLM Provider 抽象
  provider/openai.py        OpenAI 兼容协议实现（DeepSeek / 智谱）
  provider/claude.py        Anthropic Messages 协议实现
  schema/message.py         Message / ToolCall / ToolDefinition 数据模型
  tools/registry.py         工具注册中心：注册 → 暴露 Schema → 路由执行
  tools/read_file.py        读文件
  tools/write_file.py       写文件（覆盖式）
  tools/edit_file.py        局部替换（四级模糊匹配兜底）
  tools/bash.py             执行 shell 命令
  tools/path_guard.py       工作区路径守卫（防目录穿越）
tests/                      49 个单元与集成测试
demos/                      7 个独立教学小脚本
```

三个关键设计：

1. **慢思考（Thinking Phase）**：先不给模型工具，逼它输出计划；再挂载工具让它行动。计划只保留文本，不把伪工具调用写进上下文。
2. **Fork-Join 并发**：同一批工具调用若**全部只读**（`read_file`），用 `ThreadPoolExecutor` 并发执行；只要有一个涉及写，整批降级串行——宁可慢，不可错。结果用**预分配槽位**聚合，因此上下文顺序永远等于模型给出的调用顺序，且无需加锁。
3. **工具即边界**：所有异常在 Registry 内转为 `ToolResult(is_error=True)` 回传给模型，让模型自纠错，而不是让引擎崩溃。

---

## 安全设计

本项目的 `bash` 工具能执行任意命令，**只适合在本地可信环境运行**。已实现的防护：

| 防护 | 实现 |
|---|---|
| 工作区隔离 | `path_guard.resolve_in_workspace()`：`realpath` + `commonpath` 校验，拦截 `../` 穿越与绝对路径注入 |
| 密钥不泄漏 | `bash` 子进程只继承最小环境变量白名单（PATH/HOME/LANG 等），模型执行 `env` 也读不到 API Key |
| 死循环熔断 | 单任务最多 25 轮工具调用（`MAX_TURNS`） |
| 超时与截断 | bash 单命令 30 秒超时；输出截断至 8000 字符；文件读取按需截断 8000 字节 |
| 输入健壮性 | 终端输入强制 UTF-8 容错解码，编码异常不会杀死进程 |

⚠️ **未实现**：命令白名单、沙箱/容器隔离、网络访问限制。请勿在存放敏感数据的机器上让它执行不受信任的指令。

**隐私提示**：`read_file` 读到的内容会被发送到模型服务商（DeepSeek）用于推理，请勿让它读取隐私或涉密文件。

---

## 已知限制

- 上下文不做压缩，长对话会持续增长
- 无 API 重试与退避，网络抖动会让当前轮失败
- `edit_file` 写回非原子（极端情况下进程被杀可能留下半截文件）
- 仅支持单 Agent，无子 Agent / 多进程编排

---

## 许可

本项目为课程实验作业，**未附开源许可证**。代码的结构与思路来源于课程提供的 Go 版 tiny-claw，仅供学习参考；如需复用或分发，请自行补充合适的 LICENSE 并注明来源。

依赖库许可：openai (Apache-2.0)、anthropic (MIT)、pytest (MIT) 及若干 MIT / BSD / PSF 许可的传递依赖，均为宽松许可。
