#processes.py
import time
import psutil

def get_top_processes(limit=5):
    procs = []

    #check CPU counters
    for p in psutil.process_iter():
        try:
            p.cpu_percent(None)
        except:
            continue

    time.sleep(0.2)

    for p in psutil.process_iter(['pid', 'name']):
        try:
            cpu = p.cpu_percent(None)
            mem = p.memory_percent()

            procs.append({
                "pid": p.pid,
                "name": p.name(),
                "cpu_percent": round(cpu, 2),
                "memory_percent": round(mem, 2)
            })

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return sorted(
        procs,
        key=lambda x: (x['cpu_percent'], x['memory_percent']),
        reverse=True
    )[:limit]