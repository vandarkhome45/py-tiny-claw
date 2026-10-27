# demo2_parallel.py：并发 —— 3 个工人同时开工（Fork-Join）
import time
from concurrent.futures import ThreadPoolExecutor


def read(name):
    time.sleep(1)               # 假装读一个文件要 1 秒
    return name + " 读完了"


start = time.time()
names = ["a.txt", "b.txt", "c.txt"]

with ThreadPoolExecutor(max_workers=3) as executor:
    # Fork：把 3 个任务分给 3 个线程，立刻拿到 3 张"取餐小票"
    futures = [executor.submit(read, n) for n in names]
    # Join：凭小票逐个取结果，没做完就在这里等
    results = [f.result() for f in futures]

print(results)
print(f"总耗时: {time.time() - start:.1f} 秒")
