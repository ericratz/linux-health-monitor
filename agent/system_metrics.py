#system_metrics
import os
import psutil
import time
from agent.utils import format_bytes

def get_cpu_usage():
    return psutil.cpu_percent(interval=0.5)


def get_load_usage():
    load1, load5, load15 = os.getloadavg()
    return {
        "1min": round(load1, 2),
        "5min": round(load5, 2),
        "15min": round(load15, 2)
    }

def get_memory_usage():
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "used_percent": round(memory.percent, 1),
        "available_mb": round(memory.available / 1024 / 1024, 1),
        "swap_used_percent": round(swap.percent, 1)
    }


def get_disk_usage():
    disk = psutil.disk_usage("/")
    return {
        "root_used_percent": round(disk.percent, 1),
        "root_free_gb": round(disk.free / 1024 / 1024 / 1024, 1)
    }

def get_log_directory_usage(path="/var/log"):
    usage = []

    for entry in os.scandir(path):
        try:
            size = os.stat(entry.path).st_size

            usage.append({
                "name": entry.name,
                "size_bytes": size,
                "size": format_bytes(size)
            })

        except (PermissionError, FileNotFoundError):
            continue

    # sort by actual size, not string
    usage = sorted(
        usage,
        key=lambda x: x["size_bytes"],
        reverse=True
    )[:5]

    # optional: remove size_bytes from output
    for item in usage:
        item.pop("size_bytes")

    return usage

def get_log_file_usage_feature():
    try:
        return {
            "feature": "disk_details",
            "success": True,
            "data": get_log_directory_usage()
        }
    except PermissionError:
        return {
            "feature": "disk_details",
            "success": False,
            "error": "permission denied",
            "data": None
        }

def get_network_io():
    net = psutil.net_io_counters()
    return {
        "bytes_sent": format_bytes(net.bytes_sent),
        "bytes_received": format_bytes(net.bytes_recv)
    }

def get_system_uptime():
    return int(time.time() - psutil.boot_time())