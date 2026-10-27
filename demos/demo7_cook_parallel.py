# demo7_cook_parallel.py：并发做饭 —— 3 个厨师同时开工
import threading
import time
from concurrent.futures import ThreadPoolExecutor

start = time.time()

def cook(dish, minutes):
    who = threading.current_thread().name   # 是哪个线程在执行
    print(f"[{time.time() - start:.0f}秒] {who}: 开始做 {dish}")
    time.sleep(minutes)                     # 用 1 秒代表 1 分钟
    print(f"[{time.time() - start:.0f}秒] {who}: {dish} 做好了")
    return dish

menu = [("米饭", 3), ("炒青菜", 1), ("番茄蛋汤", 2)]

with ThreadPoolExecutor(max_workers=3,
                        thread_name_prefix="厨师") as executor:
    # Fork：3 道菜分给 3 个厨师
    futures = [executor.submit(cook, dish, m)
               for dish, m in menu]
    # Join：按小票顺序取菜
    results = [f.result() for f in futures]

print("上菜顺序:", results)
print(f"总耗时: {time.time() - start:.0f} 秒")
