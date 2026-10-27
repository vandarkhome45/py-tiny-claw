# demo4_slots.py：预分配列表 —— 对号入座，顺序永远正确
import random
import time
from concurrent.futures import ThreadPoolExecutor

names = ["a.txt", "b.txt", "c.txt"]
results = [None] * len(names)    # 先摆好 3 个空座位


def read(idx, name):
    time.sleep(random.random())
    results[idx] = name          # 只坐自己编号的座位


with ThreadPoolExecutor(max_workers=3) as executor:
    for i, n in enumerate(names):
        executor.submit(read, i, n)

print(results)   # 永远是 ['a.txt', 'b.txt', 'c.txt']
