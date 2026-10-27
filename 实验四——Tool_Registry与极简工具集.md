## 一、实验内容（抄写题目）

### 题目名称

实现 Tool Registry 与四大原语工具，并完成离线验证和一次综合任务。

### 题目背景

在 Agent Harness 中，Main Loop 只负责维护上下文，把模型输出的工具调用请求交给执行层。如果在 Main Loop 里用 `if call.name == "read_file": ... elif ...` 硬编码每个工具，每加一个工具就要改一次核心代码。因此需要一个 **Tool Registry**，在"模型意图（JSON）"和"系统代码"之间做一层绝缘：

- **挂载**：引擎启动时把实现了 `BaseTool` 接口的工具注册进来；
- **暴露**：每次推理前把所有工具的名称、描述、JSON Schema 打包交给 Provider；
- **分发**：收到 `ToolCall` 后按名称路由到具体工具执行，并统一封装成 `ToolResult`。

同时，工具不是越多越好。每个 Turn 模型都要把全部工具描述读一遍，工具越多，token 越贵、注意力越分散。本实验只实现 **read / write / edit / bash** 四大原语，其余能力都交给 `bash` 调用系统已有的命令行工具。

本实验分两部分：

- **离线验证**：用 `test_tools.py` 手工构造 `ToolCall` 测试 Registry 和工具，不调用大模型、不消耗 token；
- **联网验证**：只运行 1 次综合任务，让模型依次使用四个工具。

### 三个编程任务

1. 完成 `RegistryImpl`：动态挂载（Register）、描述暴露（Expose Schema）、路由分发与执行（Dispatch & Execute）。
2. 完成 `write_file` 与 `bash` 工具，其中 bash 需实现 4 个 Harness 逻辑边界：工作区约束、超时控制、自纠错回传、输出截断。
3. 完成 `edit_file` 的多级模糊匹配（L1～L4）与唯一性安全底线。

---

## 二、实验环境

| 项目 | 实际配置 |
|---|---|
| 操作系统 | macOS |
| Python | 3.14.6 |
| 依赖管理 | uv |
| OpenAI SDK | 3.16.2 |
| Anthropic SDK | 1.15.0（第 6 章新增，用于 Claude Provider） |
| 测试框架 | pytest 9.1.1 |
| 模型 | `deepseek-chat` |
| API 地址 | `https://api.deepseek.com` |
| 环境变量 | `DEEPSEEK_API_KEY` |
| 版本管理 | Git + GitHub |

环境准备命令：

```bash
cd /Users/gao_apple/py-tiny-claw/py-tiny-claw
uv sync
```

运行前确认 API Key 已配置，但不要把真实 Key 写入代码或提交到 Git：

```bash
if [[ -n "$DEEPSEEK_API_KEY" ]]; then
  echo "DEEPSEEK_API_KEY 已设置"
else
  echo "DEEPSEEK_API_KEY 未设置"
fi
```

---

## 三、代码实现

### 3.1 任务一：完成 `RegistryImpl`

文件位置：`internal/tools/registry.py`

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

要点：

1. 用 `dict[str, BaseTool]` 完成"名称 → 工具实例"的映射，彻底消除 Main Loop 里的 `if/elif` 硬编码。
2. 重复注册时打印警告并覆盖，避免同名工具静默并存导致分发歧义。
3. `execute()` 用 `try/except` 兜底：工具内部抛出的任何异常都被转换成 `is_error=True` 的 `ToolResult` 回传给模型，**绝不向上冒泡打穿引擎**——这是用例 2 要验证的核心行为。
4. 所有返回路径都回填正确的 `tool_call_id`，保证模型能把观察结果对上它发出的那次调用。

### 3.2 任务二：完成 `write_file` 与 `bash`

**`write_file` 的 `input_schema` 与 `execute()`**（`internal/tools/write_file.py`）：

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

**`bash` 的 4 个 Harness 逻辑边界**（`internal/tools/bash.py`）：

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

| 边界 | 实现 | 作用 |
|---|---|---|
| 工作区约束 | `subprocess.run(..., cwd=self.work_dir)` | 命令只在 `workspace/` 内执行，不污染项目目录 |
| 超时控制 | `timeout=30` + 捕获 `TimeoutExpired` | 防止 `sleep` / 死循环把 Agent 卡死 |
| 自纠错回传 | 非零退出码返回 `"执行报错: exit status N\n输出:\n..."` | 把真实错误信息交回模型，让它自己改命令重试 |
| 输出截断 | 超过 8000 字符截断并追加提示 | 防止 `cat` 大文件导致上下文爆炸 |

### 3.3 任务三：完成 `edit_file` 的多级模糊匹配

文件位置：`internal/tools/edit_file.py`

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

设计说明：

- **降级链解决"缩进幻觉"**：模型复述代码时经常丢掉缩进（L1 落空）、混用 `\r\n`（L2 落空）、首尾带多余空白（L3 落空），L4 逐行去缩进比对可以容忍这些偏差。
- **唯一性底线必须放在写文件之前**：`EditFileTool.execute()` 先算 `new_content = fuzzy_replace(...)`，只有匹配成功才会 `open(..., "w")` 写回。因此匹配失败时文件保持原样，不会因为 `match_start_index = -1` 而写出错乱内容。

---

## 四、任务四：离线验证（实验记录）

执行命令：

```bash
python test_tools.py
```

完整输出如下：

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

---------- 用例 1：调用不存在的工具 ----------
ToolCall  : name=delete_all, arguments={}
is_error  : True
output    : Error: 系统中不存在名为 'delete_all' 的工具。
结论      : ✅ PASS

---------- 用例 2：参数 JSON 格式错误 ----------
ToolCall  : name=read_file, arguments={path: server.py
is_error  : True
output    : Error executing read_file: 参数解析失败: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)
结论      : ✅ PASS

---------- 用例 3：bash 非零退出码 ----------
ToolCall  : name=bash, arguments={"command": "echo 出错啦 && exit 3"}
is_error  : False
output    : 执行报错: exit status 3
输出:
出错啦

结论      : ✅ PASS

---------- 用例 4：edit_file 缩进陷阱 ----------
ToolCall  : name=edit_file, arguments={"path": "server.py", "old_text": "# TODO: 增加鉴权逻辑\nif True:\nprint(\"No auth, everyone can access.\")", "new_text": "    # TODO: 增加鉴权逻辑\n    if user is None:\n        print(\"Forbidden!\")\n        return"}
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

结论      : ✅ PASS

---------- 用例 5：edit_file 唯一性底线 ----------
ToolCall  : name=edit_file, arguments={"path": "dup.py", "old_text": "x = 1", "new_text": "x = 2"}
is_error  : True
output    : Error executing edit_file: 匹配到了 2 处，请提供更多上下文
结论      : ✅ PASS

========== 测试汇总 ==========
✅ PASS  用例 1：调用不存在的工具
✅ PASS  用例 2：参数 JSON 格式错误
✅ PASS  用例 3：bash 非零退出码
✅ PASS  用例 4：edit_file 缩进陷阱
✅ PASS  用例 5：edit_file 唯一性底线
通过 5/5
```

**5 个用例全部通过。**

各用例验证的知识点对照：

| 用例 | 构造的 ToolCall | 实测结果 | 验证的知识点 |
|---|---|---|---|
| 1 | 调用不存在的 `delete_all` | `is_error=True`，output 为 `Error: 系统中不存在名为 'delete_all' 的工具。` | Registry 路由与错误回传 |
| 2 | `read_file` 参数为非法 JSON | `is_error=True`，output 为 `Error executing read_file: 参数解析失败: ...` | Registry 统一异常兜底 |
| 3 | `bash` 执行 `echo 出错啦 && exit 3` | `is_error=False`，output 含 `exit status 3` 与"出错啦" | bash 自纠错回传 |
| 4 | `edit_file` 的 `old_text` 故意丢掉缩进 | `is_error=False`，`if True:` 被替换为 `if user is None:` | 多级模糊匹配（L4 命中） |
| 5 | `old_text` 在文件中出现 2 次 | `is_error=True`，output 为"匹配到了 2 处"，文件保持不变 | 唯一性安全底线 |

### 选做：bash 超时保护

执行命令：

```bash
python test_tools.py --timeout
```

输出：

```text
（选做：bash 超时保护：请等待约 30 秒...）

---------- 选做：bash 超时保护 ----------
ToolCall  : name=bash, arguments={"command": "sleep 35"}
is_error  : False
output    : 
[警告: 命令执行超时(30s)，已被系统强制终止。]
结论      : ✅ PASS

========== 测试汇总 ==========
✅ PASS  用例 1：调用不存在的工具
✅ PASS  用例 2：参数 JSON 格式错误
✅ PASS  用例 3：bash 非零退出码
✅ PASS  用例 4：edit_file 缩进陷阱
✅ PASS  用例 5：edit_file 唯一性底线
✅ PASS  选做：bash 超时保护
通过 6/6
```

`is_error=False` 是因为超时属于"可控的边界情况"而非工具故障，输出里带上警告交由模型判断下一步，这与非零退出码的处理思路一致。

---

## 五、任务五：联网综合任务（实验记录）

执行命令：

```bash
python -m cmd.claw.main
```

运行日志（关闭慢思考模式，工作区锁定在 `workspace/`）：

```text
[Registry] 成功挂载工具: read_file
[Registry] 成功挂载工具: write_file
[Registry] 成功挂载工具: bash
[Registry] 成功挂载工具: edit_file
2026/10/16 09:18:56 [Engine] 引擎启动，锁定工作区: /Users/gao_apple/py-tiny-claw/py-tiny-claw/workspace
2026/10/16 09:18:56 [Engine] 慢思考模式 (Thinking Phase): False
2026/10/16 09:18:56 ========== [Turn 1] 开始 ==========
2026/10/16 09:18:56 [Engine][Phase 2] 恢复工具挂载，等待模型采取行动...
2026/10/16 09:18:59 HTTP Request: POST https://api.deepseek.com/chat/completions "HTTP/1.1 200 OK"
  [对外回复]: I'll complete these steps in order.

**Step 1: Create calc.py**
2026/10/16 09:18:59 [Engine] 模型请求调用 1 个工具...
2026/10/16 09:18:59  -> 🛠 执行工具: write_file, 参数: {"path": "calc.py", "content": "def add(a, b):\n    return a + b\n\n\nprint(add(2, 3))\n"}
2026/10/16 09:18:59  -> ✅ 工具执行成功 (返回 19 字节)
2026/10/16 09:18:59 ========== [Turn 2] 开始 ==========
2026/10/16 09:18:59 [Engine][Phase 2] 恢复工具挂载，等待模型采取行动...
2026/10/16 09:18:59 HTTP Request: POST https://api.deepseek.com/chat/completions "HTTP/1.1 200 OK"
  [对外回复]: **Step 2: Run python calc.py**
2026/10/16 09:19:00 [Engine] 模型请求调用 1 个工具...
2026/10/16 09:19:00  -> 🛠 执行工具: bash, 参数: {"command": "python calc.py"}
2026/10/16 09:19:00  -> ✅ 工具执行成功 (返回 2 字节)
2026/10/16 09:19:00 ========== [Turn 3] 开始 ==========
2026/10/16 09:19:00 [Engine][Phase 2] 恢复工具挂载，等待模型采取行动...
2026/10/16 09:19:01 HTTP Request: POST https://api.deepseek.com/chat/completions "HTTP/1.1 200 OK"
  [对外回复]: **Step 3: Change `return a + b` to `return a * b`**
2026/10/16 09:19:02 [Engine] 模型请求调用 1 个工具...
2026/10/16 09:19:02  -> 🛠 执行工具: edit_file, 参数: {"path": "calc.py", "old_text": "    return a + b", "new_text": "    return a * b"}
2026/10/16 09:19:02  -> ✅ 工具执行成功 (返回 17 字节)
2026/10/16 09:19:02 ========== [Turn 4] 开始 ==========
2026/10/16 09:19:02 [Engine][Phase 2] 恢复工具挂载，等待模型采取行动...
2026/10/16 09:19:03 HTTP Request: POST https://api.deepseek.com/chat/completions "HTTP/1.1 200 OK"
  [对外回复]: **Step 4: Read calc.py to confirm**
2026/10/16 09:19:03 [Engine] 模型请求调用 1 个工具...
2026/10/16 09:19:03  -> 🛠 执行工具: read_file, 参数: {"path": "calc.py"}
2026/10/16 09:19:03  -> ✅ 工具执行成功 (返回 51 字节)
2026/10/16 09:19:03 ========== [Turn 5] 开始 ==========
2026/10/16 09:19:03 [Engine][Phase 2] 恢复工具挂载，等待模型采取行动...
2026/10/16 09:19:03 HTTP Request: POST https://api.deepseek.com/chat/completions "HTTP/1.1 200 OK"
  [对外回复]: **Step 5: Run python calc.py again**
2026/10/16 09:19:04 [Engine] 模型请求调用 1 个工具...
2026/10/16 09:19:04  -> 🛠 执行工具: bash, 参数: {"command": "python calc.py"}
2026/10/16 09:19:04  -> ✅ 工具执行成功 (返回 2 字节)
2026/10/16 09:19:04 ========== [Turn 6] 开始 ==========
2026/10/16 09:19:04 [Engine][Phase 2] 恢复工具挂载，等待模型采取行动...
2026/10/16 09:19:04 HTTP Request: POST https://api.deepseek.com/chat/completions "HTTP/1.1 200 OK"
  [对外回复]: 全部完成 ✅

**两次输出分别是：**
- 第一次（`return a + b`）：**5**（2 + 3）
- 第二次（`return a * b`）：**6**（2 × 3）

修改已通过 read_file 确认生效：函数体已从 `return a + b` 变为 `return a * b`。
2026/10/16 09:19:05 [Engine] 模型未请求调用工具，任务宣告完成。
```

最终产物 `workspace/calc.py`：

```python
def add(a, b):
    return a * b


print(add(2, 3))
```

### 问题回答

**1. 日志中一共出现了几次 `🛠 执行工具`？分别调用了哪些工具？**

一共 **5 次**，按执行顺序为：

| 次序 | Turn | 工具 | 参数 |
|---|---|---|---|
| 1 | Turn 1 | `write_file` | 创建 `calc.py`，内容为 `add(a, b)` 返回 `a + b` |
| 2 | Turn 2 | `bash` | `python calc.py` |
| 3 | Turn 3 | `edit_file` | 把 `    return a + b` 替换为 `    return a * b` |
| 4 | Turn 4 | `read_file` | 读取 `calc.py` 确认修改成功 |
| 5 | Turn 5 | `bash` | 再次执行 `python calc.py` |

Turn 6 模型没有再请求工具，只做总结回复，引擎据此判定任务完成。四个原语各自被调用，`bash` 被调用了 2 次，说明 Registry 的分发与上下文累积（前一次的输出成为后一轮的输入）都工作正常。

**2. 两次运行 `calc.py` 的输出分别是多少？**

- 第一次（函数体为 `return a + b`）：**5**，即 `2 + 3 = 5`；
- 第二次（经 `edit_file` 改为 `return a * b`）：**6**，即 `2 × 3 = 6`。

两次结果不同，证明第 3 步的局部替换真实生效，且第 4 步 `read_file` 的确认与第 5 步的重新执行都基于修改后的文件状态，整条链路是连贯的。

---

## 六、思考与总结

### 第 1 题：为什么工具越多，Agent 反而可能越"笨"？

结合 Context Bloat（上下文膨胀）说明：本实验只提供 read、write、edit、bash 四大原语，这样做有什么好处？

工具越多，Agent 越笨，主要有三个原因：

**（1）上下文膨胀（Context Bloat）挤占有效信息。**

每个 Turn，模型都要把全部工具的名称、描述和 JSON Schema 完整读一遍。这些 token 是**固定开销**——无论模型这次想不想用某个工具，它都必须"看到"。工具从 4 个涨到 40 个，每轮凭空多出几千 token。上下文窗口是有限资源，被工具描述占掉的部分，就不能再用来放：

- 用户真正的需求；
- 已经读过的文件内容；
- 前面几步的执行结果与错误反馈。

于是模型在更长的上下文里"找不到重点"，反而记不住早先的关键信息。

**（2）注意力被稀释，选择质量下降。**

工具数量增长会带来**语义重叠**：读取文件到底该用 `read_file`、`cat` 还是 `python -c "open()"`？写入该用 `write_file` 还是 `echo >`？功能越相近，模型越容易在不同工具之间犹豫、来回重试，或选到一个"能用但低效"的。这本质上是把本该由系统设计者做的取舍，甩给了模型。

**（3）出错面与调试成本同步上升。**

每个工具都可能有参数解析、路径、权限、超时等问题，工具越多，出错的组合越多，Registry 的分发与异常兜底也越难排查。

**只提供四大原语的好处：**

1. **Schema 极短，固定开销最小。** 4 个工具的描述加起来只有几十行，每个 Turn 几乎不占上下文，把窗口留给真正重要的内容。
2. **图灵完备——能力无限，但不必注册。** `bash` 可以直接调用系统里已经存在的一切命令行工具（`git`、`grep`、`curl`、`ffmpeg`……）。这些能力**不需要写进 schema**，模型通过 `bash` 天然就能用。这是"用 4 个工具换来近乎无限能力"的关键：能力扩展从"改引擎 + 注册新工具 + 增加 schema"变成了"在 bash 里敲一条命令"。
3. **职责分明，不易混淆。** read 只读、write 整体覆盖写、edit 局部替换、bash 执行命令，四个动词互不重叠，模型选择时几乎没有歧义。
4. **引擎零改动。** 新增能力不再触碰 Main Loop，符合 Tool Registry 解耦"模型意图"与"系统代码"的初衷。

一句话：**工具的价值不等于工具的数量。** 用少量正交的原语 + 一个能撬动整个命令行的 `bash`，比堆砌几十个专用工具更省 token、更容易选对、也更好维护。

### 第 2 题：`edit_file` 在 `old_text` 匹配到多处时，为什么宁可报错，也不直接替换第一处？

结合 `test_tools.py` 用例 5 的运行结果说明。

用例 5 的实际情况：文件内容为 `x = 1\nprint(x)\nx = 1\n`，模型请求把 `old_text="x = 1"` 换成 `"x = 2"`。运行结果是

```text
is_error  : True
output    : Error executing edit_file: 匹配到了 2 处，请提供更多上下文
结论      : ✅ PASS
```

**文件内容保持原样，一处都没改。** 这个"拒绝"是刻意的，理由有四层：

**（1）命中多处说明模型的定位信息不足，此时"替换第一处"纯属猜测。**

模型并不是先通读文件再下笔，它给出的 `old_text` 往往来自记忆、早先的 `read_file` 片段或推测。当同一个片段出现 N 次时，模型自己也不知道它想改的是第几个。第一处**恰好**是目标位置这件事，只有 1/N 的概率——这不是执行，是赌博。

**（2）写操作的错误代价高，且不会立刻暴露。**

`edit_file` 是有副作用的写操作。如果猜错：

- 文件被静默改坏，而工具仍返回"成功"；
- 模型会基于"改成功了"的错误前提继续后面的步骤；
- 真正的故障可能要到测试、运行甚至上线后才显现，此时已经叠加了多步错误，回溯成本极高。

对比之下，**一次明确报错的代价只是多花一轮对话**。

**（3）报错本身就是有价值的信息增益。**

`"匹配到了 2 处，请提供更多上下文"` 这句话会被当作观察结果回传给模型。模型因此知道"定位不够精确"，下一次就会带上更独特的上下文——比如把 `old_text` 扩展成包含 `def add` 那一行、带上更深的缩进、或邻近的唯一代码片段。实践中第二次往往就能唯一命中。

这正是本实验反复出现的**自纠错回传**思想：`bash` 把非零退出码回传、`edit_file` 把"匹配到 N 处"回传，都是在把真实世界的状态诚实地交还给模型，让它自己修正，而不是由 Harness 替它瞎猜。

**（4）与整体防御设计保持一致。**

本实验的 Harness 里有三处同类的"拒绝盲目推进"：

| 位置 | 策略 | 共同原则 |
|---|---|---|
| `bash` 超时 | 强制终止并回传警告 | 不让 Agent 卡死在不确定里 |
| `bash` / `read_file` 输出截断 | 只回传前 8000 字符 | 不让不确定/过大的内容撑爆上下文 |
| `edit_file` 唯一性底线 | 命中多处直接报错 | 不在不确定时产生不可撤销的副作用 |

它们共同回答了同一个问题：**当系统不确定时，应该停下来告诉模型，而不是替它做一个可能错的决定。**

一句话总结：宁可暂停，不可错误推进。对只读操作可以宽松，对写操作必须保守——因为读错了可以重读，写错了不一定能撤销。

---

## 七、实验结论

本实验完成了 Tool Registry 的三大职责（挂载、暴露、分发）与四大原语工具（read / write / edit / bash）的实现，离线验证 5/5 通过（含选做用例 6/6），联网综合任务一次跑通，四个工具被依次正确调用。

三点核心收获：

1. **Registry 是"模型意图"与"系统代码"之间的绝缘层。** 有了 `dict[str, BaseTool]` 的映射与统一的 `ToolResult` 封装，新增工具只需 `registry.register(...)` 一行，Main Loop 与引擎代码零改动；工具的异常也在 Registry 这一层被统一兜底，不会打穿引擎。
2. **工具设计的重点是防御，不是功能。** 超时控制、非零退出码回传、输出截断、唯一性底线——这些"边界"才是让工具在真实 Agent 循环里可靠工作的关键。它们的作用不是让工具更强，而是让错误可控、可观测、可回传。
3. **少即是多。** 四个正交原语加上能撬动整个命令行的 `bash`，在 token 成本、选择准确率和可维护性上都优于堆砌大量专用工具。这是对抗 Context Bloat 最直接有效的手段。
