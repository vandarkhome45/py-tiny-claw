# demo3_order.py：谁先做完谁先写 —— 结果顺序会乱
import random
import time
from concurrent.futures import ThreadPoolExecutor

results = []


def read(name):
    time.sleep(random.random())  # 每个文件的耗时不一样
    results.append(name)         # 做完就往共享列表末尾追加


with ThreadPoolExecutor(max_workers=3) as executor:
    for n in ["a.txt", "b.txt", "c.txt"]:
        executor.submit(read, n)

print(results)   # 每次运行顺序都可能不同！
