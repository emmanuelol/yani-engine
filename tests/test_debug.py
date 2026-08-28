import concurrent.futures
from filelock import FileLock
lock = FileLock("test.lock")

data = ""

def worker(i):
    global data
    with lock:
        data += f"Entry {i}\n"

with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(worker, i) for i in range(20)]
    concurrent.futures.wait(futures)

print(len(data.splitlines()))
