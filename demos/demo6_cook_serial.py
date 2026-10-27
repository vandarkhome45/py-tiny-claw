# demo6_cook_serial.py：串行做饭 —— 1 个厨师按顺序做 3 道菜
import threading
import time

start = time.time()

def cook(dish, minutes):
    who = threading.current_thread().name   # 是哪个线程在执行
    print(f"[{time.time() - start:.0f}秒] {who}: 开始做 {dish}")
    time.sleep(minutes)                     # 用 1 秒代表 1 分钟
    print(f"[{time.time() - start:.0f}秒] {who}: {dish} 做好了")
    return dish

menu = [("米饭", 3), ("炒青菜", 1), ("番茄蛋汤", 2)]

results = []
for dish, m in menu:                        # 一道做完，再做下一道
    results.append(cook(dish, m))

print("上菜顺序:", results)
print(f"总耗时: {time.time() - start:.0f} 秒")
