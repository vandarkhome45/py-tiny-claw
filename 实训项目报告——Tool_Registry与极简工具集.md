# 实训项目报告

## Tool Registry 分发机制与极简工具集

| 项目 | 内容 |
|---|---|
| 课程名称 | AI 智能体开发基础 |
| 实训项目 | Tool Registry 分发机制与极简工具集（第 6 章） |
| 实训载体 | `py-tiny-claw` —— Go 版 tiny-claw 的 Python 移植版 Agent Harness |
| 建议时长 | 3 课时 |
| 姓名 | ____________ |
| 学号 | ____________ |

---

## 一、实训要求

### 1.1 实训任务

本次实训要求在一个已有的 Agent Harness（`py-tiny-claw`）上，实现工具注册中心与一套"极简工具集"，并完成离线与联网两层验证。

| 编号 | 任务 | 具体要求 |
|---|---|---|
| 任务一 | 完成 `RegistryImpl` | 实现动态挂载（Register）、描述暴露（Expose Schema）、路由分发与执行（Dispatch & Execute）三个方法 |
| 任务二 | 完成 `write_file` 与 `bash` | 补全 `write_file` 的 `input_schema` 与 `execute()`；`bash` 需实现 4 个 Harness 逻辑边界：工作区约束、超时控制、自纠错回传、输出截断 |
| 任务三 | 完成 `edit_file` 多级模糊匹配 | 实现 L1～L4 降级匹配链（精确 → 换行符归一化 → 去首尾空白 → 逐行去缩进），并坚守唯一性安全底线 |
| 任务四 | 离线验证 | 运行 `test_tools.py`，**5 个用例必须全部通过**，全程不调用大模型、不消耗 token |
| 任务五 | 联网综合任务 | 在任务四全部通过的前提下，**只运行 1 次**综合任务，让模型依次调用 read / write / edit / bash 四个工具 |

任务之间的依赖关系：**必须先完成离线验证（任务四）且 5/5 通过，再运行联网任务（任务五）**，否则只是在浪费 token。

### 1.2 技术约束与安全要求

1. **DeepSeek API Key 只能配置在环境变量里**，不得写入代码、不得提交到 Git。
2. 上传代码前必须确认待提交列表中**没有 `.env` 文件**，也没有任何包含 API Key 的文件。项目自带的 `.gitignore` 不得删除或修改。
3. 若不小心提交了 API Key，需立即到 DeepSeek 平台删除该 Key 并重新创建。
4. Windows 环境下使用 `bash` 工具需先安装 Git for Windows，并用 `bash --version` 确认命令可用。

### 1.3 提交物清单

- [x] 修改后的项目代码，上传至 GitHub 个人仓库，提交仓库链接
- [x] 实训项目报告（含实训要求、目的、器材、内容与思考总结）
- [x] `test_tools.py` 的完整运行输出
- [x] 联网综合任务的运行日志与结果分析
- [x] 确认提交列表中不含 `.env` 及 API Key

---

## 二、实训目的

本次实训围绕"工具层"展开，核心目标是理解 **Agent Harness 如何在模型意图与系统代码之间建立绝缘层**，并掌握工具设计中的防御性思维。具体目的如下：

### 目的 1：理解 Tool Registry 的作用，掌握它的三大职责

理解为什么不能在主循环里用 `if call.name == "read_file": ... elif ...` 硬编码每个工具，以及 Registry 如何用"挂载 / 暴露 / 分发"三步把模型意图（JSON）与系统代码解耦，做到**新增工具时引擎零改动**。

### 目的 2：掌握 `BaseTool` 接口契约

能够按照统一接口（`name()` / `definition()` / `execute()`）实现具体工具，并为工具编写规范的 `input_schema`（JSON Schema），使模型能够正确理解工具的参数约束。

### 目的 3：理解 Context Bloat（上下文膨胀）的危害

理解"工具不是越多越好"：每个 Turn 模型都要把全部工具描述读一遍，工具越多 token 越贵、注意力越分散。掌握由 `read`、`write`、`edit`、`bash` 构成的**图灵完备四大原语**——用最少的工具覆盖最强的能力。

### 目的 4：掌握 `bash` 工具的 4 个 Harness 逻辑边界

`bash` 是 Agent 最强大的"万能手"，同时也是最危险的工具。需要掌握四个必须实现的边界：**工作区约束**（不越界）、**超时控制**（不卡死）、**自纠错回传**（把真实错误交还模型）、**输出截断**（不撑爆上下文）。

### 目的 5：理解模型的"缩进幻觉"，实现安全的编辑能力

大模型复述代码时经常丢失或错乱缩进，直接精确匹配极易失败。需要实现 L1～L4 多级模糊匹配来容忍这些偏差，同时**坚守唯一性安全底线**：匹配到多处时宁可报错，也不猜测替换。

---

## 三、实验器材

### 3.1 硬件环境

| 器材 | 规格 |
|---|---|
| 计算机 | Apple Mac |
| 处理器 | Apple M5，10 核 |
| 内存 | 16 GB |
| 操作系统 | macOS 26.5.2（Build 25F84） |

### 3.2 软件环境

| 软件 / 依赖 | 版本 | 用途 |
|---|---|---|
| Python | 3.14.6 | 运行语言（要求 ≥ 3.10） |
| uv | — | 依赖管理与虚拟环境 |
| `openai` | 3.16.2 | 调用 OpenAI 兼容协议（DeepSeek） |
| `anthropic` | 1.15.0 | 调用 Anthropic Messages 协议（Claude Provider） |
| pytest | 9.1.1 | 自动化测试 |
| Git | 2.49.0 | 版本管理 |

依赖安装命令：

```bash
cd py-tiny-claw
uv sync
```

### 3.3 模型服务（实验"耗材"）

| 项目 | 配置 |
|---|---|
| 服务厂商 | DeepSeek |
| 模型 | `deepseek-chat` |
| 接口地址 | `https://api.deepseek.com` |
| 通信协议 | OpenAI Chat Completions 兼容协议 |
| 鉴权方式 | 环境变量 `DEEPSEEK_API_KEY` |

运行前确认：

```bash
if [[ -n "$DEEPSEEK_API_KEY" ]]; then
  echo "DEEPSEEK_API_KEY 已设置"
else
  echo "DEEPSEEK_API_KEY 未设置"
fi
```

### 3.4 开发工具

| 工具 | 说明 |
|---|---|
| PyCharm | 已安装，用于编码与运行 `main.py` |
| Visual Studio Code | 已安装，备用编辑器 |
| 终端（zsh） | 执行 `uv`、`pytest`、`test_tools.py` 等命令 |
| Typora / Obsidian | Markdown 报告编辑 |

### 3.5 实验素材

1. **老师下发的本章初始代码 `py-tiny-claw`**：包含 `internal/tools/registry.py`、`read_file.py`（已完整给出，作参考范例）、`write_file.py`、`bash.py`、`edit_file.py` 及若干 `TODO` 占位。
2. **`test_tools.py` 离线验证脚本**：手工构造 `ToolCall` 直接交给 `registry.execute()`，不调用大模型。
3. **《第6章实验报告要求_Tool_Registry与极简工具集.md》**：任务说明与提交要求。

---

## 四、实验内容

### 4.1 实训原理

#### 4.1.1 为什么需要 Tool Registry

在 Agent Harness 中，Main Loop 只负责维护上下文，把模型输出的工具调用请求交给执行层。如果直接在主循环里硬编码每个工具：

```python
if call.name == "read_file":
    ...
elif call.name == "write_file":
    ...
elif call.name == "bash":
    ...
```

那么每新增一个工具，就要改动一次核心代码，违反开闭原则，且无法独立测试。

引入 Tool Registry 后，职责被清晰地切成三部分：

| 职责 | 英文 | 说明 |
|---|---|---|
| 动态挂载 | Register | 引擎启动时把实现了 `BaseTool` 接口的工具注册进来 |
| 描述暴露 | Expose Schema | 每次推理前把所有工具的名称、描述、JSON Schema 打包交给 Provider |
| 路由分发与执行 | Dispatch & Execute | 收到 `ToolCall` 后按名称路由到具体工具执行，并统一封装成 `ToolResult` |

#### 4.1.2 系统分层

```text
cmd/claw/main.py                 入口：组装 Registry、挂载工具、下达任务
        ↓
internal/engine/loop.py          AgentEngine 主循环：Reason → Act → Observe
        ↓                 ↓
internal/provider/        internal/tools/
  interface.py              registry.py（BaseTool / Registry / RegistryImpl）
  openai.py                 read_file.py / write_file.py / bash.py / edit_file.py
  claude.py
        ↓
internal/schema/message.py       统一消息模型：Message / ToolCall / ToolResult / ToolDefinition
```

`internal/schema/message.py` 是与厂商无关的内部统一格式，Provider 负责与具体模型协议互转，Registry 负责与具体工具实现互转——两侧都被绝缘，Main Loop 保持稳定。

#### 4.1.3 四大原语与 Context Bloat

工具不是越多越好。每个 Turn 模型都要把全部工具描述读一遍，工具越多：

- token 成本越高；
- 注意力越分散，越容易选错工具；
- 出错面与调试成本越大。

因此本实训只实现 **read / write / edit / bash** 四大原语，其余能力全部交给 `bash` 调用系统已有的命令行工具——这些能力**不需要注册进 schema**，模型通过 `bash` 天然就能使用。

---

### 4.2 任务一：完成 `RegistryImpl`

**文件位置**：`internal/tools/registry.py`

```python
class RegistryImpl(Registry):
    """Registry 的默认实现：内部用一个 dict 存储 名称 -> 工具实例 的映射"""

    def __init__(self):
        self.tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        # 职责 1：动态挂载（Register）
        tool_name = tool.name()

        if tool_name in self.tools:
            print(f"[Warning] 工具 '{tool_name}' 已经被注册，将被覆盖。")

        self.tools[tool_name] = tool
        print(f"[Registry] 成功挂载工具: {tool_name}")

    def get_available_tools(self) -> list[ToolDefinition]:
        # 职责 2：描述暴露（Expose Schema）
        return [tool.definition() for tool in self.tools.values()]

    def execute(self, call: ToolCall) -> ToolResult:
        # 职责 3：路由分发与执行（Dispatch & Execute）
        tool = self.tools.get(call.name)

        if tool is None:
            return ToolResult(
                tool_call_id=call.id,
                output=f"Error: 系统中不存在名为 '{call.name}' 的工具。",
                is_error=True,
            )

        try:
            output = tool.execute(call.arguments)
        except Exception as e:
            # 关键防线：任何工具异常都在此转换为错误结果，绝不让引擎崩溃
            return ToolResult(
                tool_call_id=call.id,
                output=f"Error executing {call.name}: {e}",
                is_error=True,
            )

        return ToolResult(tool_call_id=call.id, output=output, is_error=False)
```

**实现要点**

1. 用 `dict[str, BaseTool]` 完成"名称 → 工具实例"映射，彻底消除主循环中的 `if/elif` 硬编码。
2. 重复注册时打印警告并覆盖，避免同名工具静默并存导致分发歧义。
3. `execute()` 用 `try/except` 兜底：工具抛出的任何异常都转为 `is_error=True` 的 `ToolResult`，**绝不向上冒泡打穿引擎**。
4. 所有返回路径都回填正确的 `tool_call_id`，保证模型能把观察结果对上它发出的那次调用。

---

### 4.3 任务二：完成 `write_file` 与 `bash`

#### 4.3.1 `write_file`

**文件位置**：`internal/tools/write_file.py`

补全 `input_schema`（`path` 与 `content` 两个必填字符串参数），并实现 `execute()`：

```python
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name(),
            description="创建或覆盖写入一个文件。如果目录不存在会自动创建。请提供相对于工作区的相对路径。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要写入的文件路径，如 hello.py"},
                    "content": {"type": "string", "description": "要写入文件的完整内容"},
                },
                "required": ["path", "content"],
            },
        )

    def execute(self, args: str) -> str:
        try:
            input_args = json.loads(args)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"参数解析失败: {e}") from e

        rel_path = input_args.get("path", "")
        content = input_args.get("content", "")

        full_path = os.path.join(self.work_dir, rel_path)

        parent = os.path.dirname(full_path)
        if parent:
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError as e:
                raise RuntimeError(f"创建目录失败: {e}") from e

        try:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            raise RuntimeError(f"写入文件失败: {e}") from e

        return f"成功将内容写入到文件: {rel_path}"
```

要点：路径一律用 `os.path.join(self.work_dir, path)` 拼接到工作区内；父目录用 `os.makedirs(..., exist_ok=True)` 自动创建；失败时抛 `RuntimeError`，由 Registry 统一兜底。

#### 4.3.2 `bash` —— 4 个 Harness 逻辑边界

**文件位置**：`internal/tools/bash.py`

```python
TIMEOUT_SECONDS = 30
MAX_OUTPUT_CHARS = 8000


    def execute(self, args: str) -> str:
        try:
            input_args = json.loads(args)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"参数解析失败: {e}") from e

        command = input_args.get("command", "")

        # 边界 1：工作区约束（cwd）+ 边界 2：超时控制（timeout=30s）
        try:
            completed = subprocess.run(
                ["bash", "-c", command],
                cwd=self.work_dir,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as e:
            # 超时不算"异常"，把已有输出连同警告一起回传，让模型自己决定下一步
            partial = _merge_output(e.stdout, e.stderr)
            return _truncate(
                partial
                + f"\n[警告: 命令执行超时({TIMEOUT_SECONDS}s)，已被系统强制终止。]"
            )

        output = _merge_output(completed.stdout, completed.stderr)

        # 边界 3：自纠错回传 —— 非零退出码原样回传，而不是抛异常
        if completed.returncode != 0:
            return _truncate(
                f"执行报错: exit status {completed.returncode}\n输出:\n{output}"
            )

        # 边界 4：输出为空时的明确提示
        if output.strip() == "":
            return "命令执行成功，无终端输出。"

        return _truncate(output)
```

| 边界 | 实现 | 解决的问题 |
|---|---|---|
| 工作区约束 | `subprocess.run(..., cwd=self.work_dir)` | 命令只在 `workspace/` 内执行，不污染项目目录 |
| 超时控制 | `timeout=30` + 捕获 `TimeoutExpired` | 防止 `sleep` / 死循环把 Agent 永久卡死 |
| 自纠错回传 | 非零退出码返回 `"执行报错: exit status N\n输出:\n..."` | 把真实错误信息交回模型，让它自己改命令重试 |
| 输出截断 | 超过 8000 字符截断并追加提示 | 防止 `cat` 大文件导致上下文爆炸 |

**为什么非零退出码不抛异常**：退出码非 0 是命令的**正常反馈**，不是工具故障。把它原样回传，模型才能看到"命令不存在""权限不足"等真实原因并自行纠正——这正是"自纠错回传"的价值。

---

### 4.4 任务三：完成 `edit_file` 的多级模糊匹配

**文件位置**：`internal/tools/edit_file.py`

```python
def fuzzy_replace(original_content: str, old_text: str, new_text: str) -> str:
    """四级降级匹配：精确 -> 换行符归一化 -> 去首尾空白 -> 逐行去缩进

    任一级「恰好命中 1 处」就替换并返回；命中多处一律报错，绝不猜测。
    """
    # ---------- L1 精确匹配 ----------
    count = original_content.count(old_text)
    if count == 1:
        return original_content.replace(old_text, new_text, 1)
    if count > 1:
        raise RuntimeError(f"匹配到了 {count} 处，请提供更多上下文")

    # ---------- L2 换行符归一化（\r\n -> \n）----------
    normalized_content = original_content.replace("\r\n", "\n")
    normalized_old = old_text.replace("\r\n", "\n")

    count = normalized_content.count(normalized_old)
    if count == 1:
        return normalized_content.replace(normalized_old, new_text, 1)
    if count > 1:
        raise RuntimeError(f"匹配到了 {count} 处，请提供更多上下文")

    # ---------- L3 整体去首尾空白 ----------
    stripped_old = normalized_old.strip()
    if stripped_old != "":
        count = normalized_content.count(stripped_old)
        if count == 1:
            return normalized_content.replace(stripped_old, new_text, 1)
        if count > 1:
            raise RuntimeError(f"匹配到了 {count} 处，请提供更多上下文")

    # ---------- L4 逐行去缩进匹配 ----------
    return line_by_line_replace(normalized_content, old_text, new_text)
```

`line_by_line_replace()` 中的唯一性安全底线：

```python
    # 唯一性安全底线：0 处报"找不到"，多于一处一律拒绝修改
    if match_count == 0:
        raise RuntimeError("在文件中未找到 old_text，请检查内容和缩进")
    if match_count > 1:
        raise RuntimeError(f"模糊匹配到了 {match_count} 处代码，请提供更多上下文以定位")
```

| 级别 | 策略 | 容忍的"模型幻觉" |
|---|---|---|
| L1 | 精确匹配 | 无（理想情况） |
| L2 | `\r\n` 统一归一化为 `\n` | 换行符风格不一致 |
| L3 | 对 `old_text` 做整体 `strip()` | 首尾多了/少了空白 |
| L4 | 逐行去缩进后比对 | **缩进幻觉**（缩进丢失或偏差） |

**关键的时序保证**：`EditFileTool.execute()` 先计算 `new_content = fuzzy_replace(...)`，只有匹配成功才会 `open(..., "w")` 写回。因此匹配失败时文件保持原样，不会因为 `match_start_index = -1` 而写出错乱内容。

---

### 4.5 离线验证（任务四）

执行命令：

```bash
python test_tools.py
```

脚本挂载四个工具后，手工构造 `ToolCall` 直接交给 `registry.execute()`，全程不调用大模型。

#### 4.5.1 挂载结果

```text
========== 准备：挂载四大原语 ==========
[Registry] 成功挂载工具: read_file
[Registry] 成功挂载工具: write_file
[Registry] 成功挂载工具: bash
[Registry] 成功挂载工具: edit_file
暴露给模型的工具数量: 4
  - read_file: 读取指定路径的文件内容。请提供相对工作区的路径。
  - write_file: 创建或覆盖写入一个文件。如果目录不存在会自动创建。请提供相对于工作区的相对路径。
  - bash: 在当前工作区执行任意的 bash 命令。支持链式命令(如 &&)。返回标准输出(stdout)和标准错误(stderr)。
  - edit_file: 对现有文件进行局部的字符串替换。这比重写整个文件更安全、更快速。请提供足够的 old_text 上下文以确保匹配的唯一性。
```

#### 4.5.2 五个用例结果

| 用例 | 构造的 ToolCall | 实测结果 | 验证的知识点 |
|---|---|---|---|
| 1 | 调用不存在的 `delete_all` | `is_error=True`；`Error: 系统中不存在名为 'delete_all' 的工具。` | Registry 路由与错误回传 |
| 2 | `read_file` 参数为非法 JSON `{path: server.py` | `is_error=True`；`Error executing read_file: 参数解析失败: ...` | Registry 统一异常兜底 |
| 3 | `bash` 执行 `echo 出错啦 && exit 3` | `is_error=False`；输出含 `exit status 3` 与"出错啦" | bash 自纠错回传 |
| 4 | `edit_file` 的 `old_text` 故意丢掉全部缩进 | `is_error=False`；`if True:` 被替换为 `if user is None:` | 多级模糊匹配（L4 命中） |
| 5 | `old_text` 在文件中出现 2 次 | `is_error=True`；"匹配到了 2 处，请提供更多上下文"；**文件保持不变** | 唯一性安全底线 |

关键用例细节摘录：

```text
---------- 用例 4：edit_file 缩进陷阱 ----------
is_error  : False
output    : ✅ 成功修改文件: server.py
修改后的 server.py:
def main():
    # 启动服务器
    print("Server is starting on port 8080...")
    # TODO: 增加鉴权逻辑
    if user is None:
        print("Forbidden!")
        return

if __name__ == "__main__":
    main()

---------- 用例 5：edit_file 唯一性底线 ----------
is_error  : True
output    : Error executing edit_file: 匹配到了 2 处，请提供更多上下文
```

#### 4.5.3 测试汇总

```text
========== 测试汇总 ==========
✅ PASS  用例 1：调用不存在的工具
✅ PASS  用例 2：参数 JSON 格式错误
✅ PASS  用例 3：bash 非零退出码
✅ PASS  用例 4：edit_file 缩进陷阱
✅ PASS  用例 5：edit_file 唯一性底线
通过 5/5
```

**5 个用例全部通过。**

#### 4.5.4 选做：bash 超时保护

执行 `python test_tools.py --timeout`，额外执行 `sleep 35`：

```text
---------- 选做：bash 超时保护 ----------
ToolCall  : name=bash, arguments={"command": "sleep 35"}
is_error  : False
output    : 
[警告: 命令执行超时(30s)，已被系统强制终止。]
结论      : ✅ PASS

通过 6/6
```

---

### 4.6 联网综合任务（任务五）

在任务四 5/5 通过后运行（关闭慢思考模式以节省 token，工作区锁定在 `workspace/`）：

```bash
python -m cmd.claw.main
```

#### 4.6.1 运行日志（节选）

```text
2026/10/16 09:18:56 [Engine] 引擎启动，锁定工作区: .../py-tiny-claw/workspace
2026/10/16 09:18:56 [Engine] 慢思考模式 (Thinking Phase): False

========== [Turn 1] 开始 ==========
  -> 🛠 执行工具: write_file, 参数: {"path": "calc.py", "content": "def add(a, b):\n    return a + b\n\n\nprint(add(2, 3))\n"}
  -> ✅ 工具执行成功 (返回 19 字节)

========== [Turn 2] 开始 ==========
  -> 🛠 执行工具: bash, 参数: {"command": "python calc.py"}
  -> ✅ 工具执行成功 (返回 2 字节)

========== [Turn 3] 开始 ==========
  -> 🛠 执行工具: edit_file, 参数: {"path": "calc.py", "old_text": "    return a + b", "new_text": "    return a * b"}
  -> ✅ 工具执行成功 (返回 17 字节)

========== [Turn 4] 开始 ==========
  -> 🛠 执行工具: read_file, 参数: {"path": "calc.py"}
  -> ✅ 工具执行成功 (返回 51 字节)

========== [Turn 5] 开始 ==========
  -> 🛠 执行工具: bash, 参数: {"command": "python calc.py"}
  -> ✅ 工具执行成功 (返回 2 字节)

========== [Turn 6] 开始 ==========
  [对外回复]: 全部完成 ✅
**两次输出分别是：**
- 第一次（`return a + b`）：**5**（2 + 3）
- 第二次（`return a * b`）：**6**（2 × 3）
2026/10/16 09:19:05 [Engine] 模型未请求调用工具，任务宣告完成。
```

#### 4.6.2 最终产物

`workspace/calc.py`：

```python
def add(a, b):
    return a * b


print(add(2, 3))
```

#### 4.6.3 任务结果分析

**问题一：日志中一共出现了几次 `🛠 执行工具`？分别调用了哪些工具？**

一共 **5 次**，共 6 个 Turn：

| 次序 | Turn | 工具 | 作用 |
|---|---|---|---|
| 1 | Turn 1 | `write_file` | 创建 `calc.py` |
| 2 | Turn 2 | `bash` | 执行 `python calc.py` |
| 3 | Turn 3 | `edit_file` | 把 `return a + b` 改为 `return a * b` |
| 4 | Turn 4 | `read_file` | 读回确认修改生效 |
| 5 | Turn 5 | `bash` | 再次执行 `python calc.py` |

Turn 6 模型不再请求工具，直接总结，引擎据此判定任务完成。四个原语均被正确调用（`bash` 被调用 2 次），说明 Registry 的分发与上下文累积（上一步的输出成为下一步的输入）都工作正常。

**问题二：两次运行 `calc.py` 的输出分别是多少？**

- 第一次（`return a + b`）：**5**，即 `2 + 3 = 5`；
- 第二次（改为 `return a * b` 后）：**6**，即 `2 × 3 = 6`。

两次结果不同，证明第 3 步的局部替换真实生效，且第 4 步确认、第 5 步重跑都基于修改后的文件状态，整条链路连贯。

---

### 4.7 实训中遇到的问题与解决

#### 问题 1：`python -m cmd.claw.main` 无法启动

**现象**

```text
ModuleNotFoundError: No module named 'cmd.claw'; 'cmd' is not a package
```

**原因**：项目根目录下的 `cmd/` 包与 **Python 标准库的 `cmd` 模块同名**。当 `cmd/` 目录下缺少 `__init__.py` 时，按 PEP 420 它只是一个"命名空间包候选"，导入扫描会继续向后找，最终命中标准库的 `cmd.py`（普通模块优先），于是 `cmd.claw` 找不到。该问题在老师下发的原始代码中同样存在。

**解决**：补上 `cmd/__init__.py` 使其成为常规包。

#### 问题 2：补上 `__init__.py` 后 pytest 崩溃

**现象**

```text
AttributeError: module 'cmd' has no attribute 'Cmd'
```

**原因**：有了 `__init__.py`，项目根目录一旦位于 `sys.path` 最前面（如执行 `python -m pytest`），本项目的 `cmd/` 就会**遮蔽**标准库 `cmd`；而 pytest 内部依赖 `pdb`，`pdb` 又依赖 `cmd.Cmd`，于是崩溃。

**解决**（三处配合）：

1. `cmd/__init__.py` 中按文件路径加载标准库 `cmd.py`，把其公开成员并入本包命名空间，使 `pdb` 等仍可正常工作；
2. `pyproject.toml` 移除 `pythonpath = ["."]`，改由 `tests/conftest.py` 把项目根目录**追加**到 `sys.path` 末尾而非插到最前；
3. `cmd/claw/main.py` 中的路径插入增加"不存在才插"的判断，避免重复插入。

**结果**：`uv run pytest`、`python -m pytest`、`python -m cmd.claw.main`、`python cmd/claw/main.py`、`python test_tools.py` 五种调用方式全部可用。

#### 问题 3：`ClaudeProvider` 未继承 `LLMProvider`

老师下发代码中 `ClaudeProvider` 是独立类，未继承 `LLMProvider` 抽象接口，与 `OpenAIProvider` 的契约不一致。已补上继承关系，使两个 Provider 遵循同一接口。

---

### 4.8 思考题解析

#### 思考题 1：为什么工具越多，Agent 反而可能越"笨"？

三层原因：

**① 上下文膨胀（Context Bloat）挤占有效信息。** 每个 Turn 模型都要把全部工具的名称、描述、JSON Schema 完整读一遍，这部分是**固定开销**——无论本次用不用都得"看到"。工具从 4 个涨到 40 个，每轮凭空多出几千 token。上下文窗口有限，被工具描述占掉的部分就不能再用来存放用户需求、已读文件内容和历史执行结果，模型于是在更长的上下文里"找不到重点"。

**② 注意力被稀释，选择质量下降。** 工具数量增长必然带来**语义重叠**：读文件该用 `read_file`、`cat` 还是 `python -c "open()"`？功能越相近，模型越容易犹豫、来回重试，或选到"能用但低效"的那一个。这本质上是把本该由系统设计者做的取舍甩给了模型。

**③ 出错面与调试成本同步上升。** 每个工具都可能有参数、路径、权限、超时等问题，工具越多，出错组合越多，Registry 的分发与兜底也越难排查。

**只提供四大原语的好处：**

1. **Schema 极短**，每轮固定开销最小，把窗口留给真正重要的内容；
2. **图灵完备**——`bash` 可以调用系统里已存在的一切命令（`git`、`grep`、`curl`……），这些能力不需要写进 schema，模型通过 `bash` 天然可用。**用 4 个工具换来近乎无限的能力**；
3. **职责正交**（read 只读 / write 整体覆盖 / edit 局部替换 / bash 执行命令），选择时几乎没有歧义；
4. **扩展时引擎零改动**，符合 Registry 解耦的初衷。

#### 思考题 2：`edit_file` 匹配到多处时，为什么宁可报错也不替换第一处？

以用例 5 为例：文件为 `x = 1\nprint(x)\nx = 1\n`，模型请求把 `x = 1` 换成 `x = 2`，结果为 `is_error=True`、`匹配到了 2 处`、**文件一处没改**。这个"拒绝"是刻意的：

**① 命中多处说明模型定位不足，选第一处是赌博。** 模型的 `old_text` 常来自记忆或早先片段，当同一片段出现 N 次时它自己也不知道想改第几个，"恰好是第一处"只有 1/N 的概率。

**② 写操作的错误代价高且不立即暴露。** 若猜错：文件被静默改坏而工具仍报"成功" → 模型基于错误前提继续后续步骤 → 故障可能到测试甚至运行阶段才显现，此时已叠加多步错误，回溯成本极高。相比之下，一次明确报错的代价只是多花一轮对话。

**③ 报错本身是信息增益。** `"匹配到了 2 处，请提供更多上下文"` 会作为观察结果回传，模型知道"定位不够精确"后，下一轮会带上更独特的上下文（如包含 `def` 行、更深缩进、邻近唯一片段），往往第二次就能唯一命中。这与 `bash` 回传非零退出码是同一套**自纠错回传**思想。

**④ 与整体防御设计一致。**

| 位置 | 策略 | 共同原则 |
|---|---|---|
| `bash` 超时 | 强制终止并回传警告 | 不让 Agent 卡死在不确定里 |
| 输出截断 | 只回传前 8000 字符 | 不让过大内容撑爆上下文 |
| `edit_file` 唯一性底线 | 命中多处直接报错 | 不在不确定时产生不可撤销的副作用 |

共同回答了同一个问题：**当系统不确定时，应该停下来告诉模型，而不是替它做一个可能错的决定。** 读错了可以重读，写错了不一定能撤销。

---

## 五、实训总结

### 5.1 完成情况

| 任务 | 状态 |
|---|---|
| 任务一：`RegistryImpl` 三个职责 | 完成 |
| 任务二：`write_file` + `bash`（4 个边界） | 完成 |
| 任务三：`edit_file` L1～L4 模糊匹配 + 唯一性底线 | 完成 |
| 任务四：离线验证 | 5/5 通过（含选做 6/6） |
| 任务五：联网综合任务 | 一次跑通，5 次工具调用，输出 5 与 6 |
| pytest 自动化测试 | 全量 32 项通过（本次新增 24 项 + 前期实验遗留 8 项） |

### 5.2 主要收获

1. **Registry 是"模型意图"与"系统代码"之间的绝缘层。** 有了 `dict[str, BaseTool]` 映射与统一的 `ToolResult` 封装，新增工具只需 `registry.register(...)` 一行，Main Loop 与引擎代码零改动；工具的异常也在这一层被统一兜底，不会打穿引擎。

2. **工具设计的重点是防御，不是功能。** 超时控制、非零退出码回传、输出截断、唯一性底线——这些"边界"才是让工具在真实 Agent 循环里可靠工作的关键。它们的作用不是让工具更强，而是让错误**可控、可观测、可回传**。

3. **少即是多。** 四个正交原语加上能撬动整个命令行的 `bash`，在 token 成本、选择准确率和可维护性上都优于堆砌大量专用工具，这是对抗 Context Bloat 最直接有效的手段。

4. **错误信息要给得诚实。** 无论是 bash 的 `exit status N` 还是 edit_file 的"匹配到了 2 处"，把真实状态交还模型、让它自己修正，远好过由系统替它猜测——这是本次实训反复出现、也最值得记住的一条。

### 5.3 不足与改进方向

1. **引擎仍无最大轮次上限**，模型若陷入工具循环可能一直运行下去，可增加 `max_turns` 保护。
2. **`work_dir` 是约定而非沙箱**，`bash` 可用 `cd /` 或绝对路径绕过工作区限制；生产环境需要更强的隔离（容器 / 权限白名单）。
3. **思考阶段（Phase 1）的文本会永久写入上下文**，在多轮任务中可能污染后续判断，可考虑只在最后一轮保留或单独存放。
