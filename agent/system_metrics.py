#system_metrics.py
import os
import psutil
import time

def get_cpu_usage():
    """
    Returns CPU usage over a 0.5 second interval as a percentage.
    """
    return psutil.cpu_percent(interval=0.5)


def get_load_average():
    """
    Returns the system load average over 1, 5, and 15 minutes.
    """
    load1, load5, load15 = os.getloadavg()
    return {
        "1min": round(load1, 2),
        "5min": round(load5, 2),
        "15min": round(load15, 2)
    }

def get_memory_usage():
    """
    Returns the current system memory and swap usage.
    """
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "used_percent": round(memory.percent, 2),
        "available": memory.available,
        "swap_used_percent": round(swap.percent, 2)
    }


def get_disk_usage():
    """
    Returns the current disk usage for the root partition.
    """
    disk = psutil.disk_usage("/")
    return {
        "root_used_percent": round(disk.percent, 2),
        "root_free": disk.free
    }

def get_directory_usage(path="/var/log"):
    """
    Scans a directory and returns the size of the largest files.
    """
    usage = []
    for entry in os.scandir(path):
        try:
            size = os.stat(entry.path).st_size
            usage.append({
                "name": entry.name,
                "size_bytes": size
            })
        except (PermissionError, FileNotFoundError):
            continue
    #sort by size
    usage = sorted(
        usage,
        key=lambda x: x["size_bytes"],
        reverse=True
    )[:5]
    return usage

def get_network_io():
    """
    Returns total network I/O statistics.
    """
    net = psutil.net_io_counters()
    return {
        "bytes_sent": net.bytes_sent,
        "bytes_received": net.bytes_recv
    }

def get_system_uptime():
    """
    Returns the system uptime in seconds since last boot.
    """
    return int(time.time() - psutil.boot_time())


def get_top_processes(limit=5):
    """
    Returns the top processes by CPU and memory usage.
    """
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