# test_tools.py
# 第 6 章离线验证脚本：不调用大模型、不消耗任何 token。
# 手工构造 ToolCall 直接交给 registry.execute()，验证 Registry 分发与工具的容错逻辑。
#
# 运行方式（在 py-tiny-claw 目录下）:
#   python test_tools.py            # 运行用例 1～5
#   python test_tools.py --timeout  # 额外运行选做用例：bash 30 秒超时（需要等待约 30 秒）
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from internal.schema.message import ToolCall
from internal.tools.bash import BashTool
from internal.tools.edit_file import EditFileTool
from internal.tools.read_file import ReadFileTool
from internal.tools.registry import new_registry
from internal.tools.write_file import WriteFileTool

# 用于缩进陷阱的测试文件：真实代码带 4/8 空格缩进
SERVER_CODE = '''def main():
    # 启动服务器
    print("Server is starting on port 8080...")
    # TODO: 增加鉴权逻辑
    if True:
        print("No auth, everyone can access.")

if __name__ == "__main__":
    main()
'''

results = []


def show(title: str, call: ToolCall, result):
    print(f"\n---------- {title} ----------")
    print(f"ToolCall  : name={call.name}, arguments={call.arguments}")
    if result is None:
        print("ToolResult: None（execute 还没有返回 ToolResult，请检查 Registry 实现）")
        return
    print(f"is_error  : {result.is_error}")
    print(f"output    : {result.output}")


def check(title: str, ok: bool):
    results.append((title, ok))
    print(f"结论      : {'✅ PASS' if ok else '❌ FAIL'}")


def run_case(title: str, func):
    """单个用例出现异常时只判 FAIL，不影响后续用例"""
    try:
        func(title)
    except Exception as e:
        print(f"\n---------- {title} ----------")
        print(f"用例运行时抛出异常（说明异常没有被 Registry 兜底）: {type(e).__name__}: {e}")
        check(title, False)


def main():
    run_timeout = "--timeout" in sys.argv

    # 使用临时目录作为工作区，测试结束自动删除，不会弄乱项目
    with tempfile.TemporaryDirectory() as work_dir:
        print("========== 准备：挂载四大原语 ==========")
        registry = new_registry()
        registry.register(ReadFileTool(work_dir))
        registry.register(WriteFileTool(work_dir))
        registry.register(BashTool(work_dir))
        registry.register(EditFileTool(work_dir))

        tools = registry.get_available_tools() or []
        print(f"暴露给模型的工具数量: {len(tools)}")
        for t in tools:
            print(f"  - {t.name}: {t.description}")

        # 用例 1：调用不存在的工具
        def case1(title):
            call = ToolCall(id="call_1", name="delete_all", arguments="{}")
            r = registry.execute(call)
            show(title, call, r)
            check(title, r is not None and r.is_error and r.tool_call_id == "call_1"
                  and "delete_all" in r.output)

        # 用例 2：参数不是合法 JSON（工具内部抛异常，应被 Registry 兜底）
        def case2(title):
            call = ToolCall(id="call_2", name="read_file", arguments="{path: server.py")
            r = registry.execute(call)
            show(title, call, r)
            check(title, r is not None and r.is_error and r.tool_call_id == "call_2")

        # 用例 3：bash 非零退出码应原样回传，而不是抛异常
        def case3(title):
            call = ToolCall(id="call_3", name="bash", arguments='{"command": "echo 出错啦 && exit 3"}')
            r = registry.execute(call)
            show(title, call, r)
            check(title, r is not None and not r.is_error
                  and "exit status 3" in r.output and "出错啦" in r.output)

        # 用例 4：缩进陷阱 —— old_text 故意丢掉全部缩进，应在 L4 逐行去缩进匹配中命中
        def case4(title):
            with open(os.path.join(work_dir, "server.py"), "w", encoding="utf-8") as f:
                f.write(SERVER_CODE)
            old_text = "# TODO: 增加鉴权逻辑\nif True:\nprint(\"No auth, everyone can access.\")"
            new_text = ("    # TODO: 增加鉴权逻辑\n"
                        "    if user is None:\n"
                        "        print(\"Forbidden!\")\n"
                        "        return")
            import json
            args = json.dumps({"path": "server.py", "old_text": old_text, "new_text": new_text},
                              ensure_ascii=False)
            call = ToolCall(id="call_4", name="edit_file", arguments=args)
            r = registry.execute(call)
            show(title, call, r)
            with open(os.path.join(work_dir, "server.py"), encoding="utf-8") as f:
                after = f.read()
            print("修改后的 server.py:\n" + after)
            check(title, r is not None and not r.is_error
                  and "if user is None:" in after and "if True:" not in after)

        # 用例 5：唯一性底线 —— old_text 在文件中出现 2 次，必须报错且文件保持不变
        def case5(title):
            original = "x = 1\nprint(x)\nx = 1\n"
            path = os.path.join(work_dir, "dup.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(original)
            call = ToolCall(id="call_5", name="edit_file",
                            arguments='{"path": "dup.py", "old_text": "x = 1", "new_text": "x = 2"}')
            r = registry.execute(call)
            show(title, call, r)
            with open(path, encoding="utf-8") as f:
                after = f.read()
            check(title, r is not None and r.is_error and after == original)

        # 选做：bash 30 秒超时保护
        def case_timeout(title):
            call = ToolCall(id="call_6", name="bash", arguments='{"command": "sleep 35"}')
            print(f"\n（{title}：请等待约 30 秒...）")
            r = registry.execute(call)
            show(title, call, r)
            check(title, r is not None and "超时" in r.output)

        run_case("用例 1：调用不存在的工具", case1)
        run_case("用例 2：参数 JSON 格式错误", case2)
        run_case("用例 3：bash 非零退出码", case3)
        run_case("用例 4：edit_file 缩进陷阱", case4)
        run_case("用例 5：edit_file 唯一性底线", case5)
        if run_timeout:
            run_case("选做：bash 超时保护", case_timeout)

    print("\n========== 测试汇总 ==========")
    for title, ok in results:
        print(f"{'✅ PASS' if ok else '❌ FAIL'}  {title}")
    passed = sum(1 for _, ok in results if ok)
    print(f"通过 {passed}/{len(results)}")


if __name__ == "__main__":
    main()
