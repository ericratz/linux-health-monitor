#shell.py - shared subprocess wrapper
import shutil
import subprocess

#Resolved binaries are cached: a collection run asks about the same handful of
#tools repeatedly, and PATH does not change mid-run.
_HAVE_CACHE = {}


def have(command):
    """
    True if a command exists on PATH.

    Used to pick between family-specific tools (apt vs dnf, ufw vs
    firewall-cmd) and to skip a check entirely rather than shelling out to
    something that is not installed.
    """
    if command not in _HAVE_CACHE:
        _HAVE_CACHE[command] = shutil.which(command) is not None
    return _HAVE_CACHE[command]


def run_command(command, timeout=3):
    """
    Runs a command and returns the result.

    Never raises: a missing binary, a non-zero exit, or a hang past the
    timeout all come back as success=False so callers can degrade gracefully.
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout
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
