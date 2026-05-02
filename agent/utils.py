#utilities
import subprocess
from datetime import datetime, timezone

def get_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_command(command):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3
        )
        return {
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
            "success": result.returncode == 0
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": "Command timed out",
            "returncode": -1,
            "success": False
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "returncode": -1,
            "success": False
        }
    

def safe_run(name, fn, fallback=None):
    try:
        return {
            "feature": name,
            "success": True,
            "data": fn()
        }
    except Exception as e:
        return {
            "feature": name,
            "success": False,
            "error": str(e),
            "fallback": fallback
        }

def format_bytes(num):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"