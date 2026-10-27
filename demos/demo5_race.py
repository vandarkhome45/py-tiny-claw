# demo5_race.py：写和读同时进行 ——「先写后读」不再有保证
import os
import time
from concurrent.futures import ThreadPoolExecutor

if os.path.exists("d.txt"):
    os.remove("d.txt")           # 先确保 d.txt 不存在

def write_file():
    time.sleep(0.1)              # 写磁盘需要一点时间
    with open("d.txt", "w", encoding="utf-8") as f:
        f.write("这是文件D")
    return "写入成功"

def read_file():
    if not os.path.exists("d.txt"):
        return "❌ 文件不存在！"
    with open("d.txt", encoding="utf-8") as f:
        return f.read()

with ThreadPoolExecutor(max_workers=2) as executor:
    f1 = executor.submit(write_file)   # 模型的本意：先写
    f2 = executor.submit(read_file)    # 再读
    print("写:", f1.result())
    print("读:", f2.result())
