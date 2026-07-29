#system_context.py
from agent.system_metrics import get_directory_usage
from agent.shell import run_command
import os
import platform
import re

#Container runtimes to probe, in order. node1 runs Docker; node2 runs rootless
#Podman and has no docker binary at all.
CONTAINER_RUNTIMES = ("docker", "podman")

#Overridden per host with HEALTH_SERVICES.
DEFAULT_SERVICES = ["nginx", "docker"]

#os-release ID / ID_LIKE tokens mapped to the family whose tooling applies.
#Only families whose commands actually differ need an entry.
OS_FAMILIES = {
    "debian": "debian",
    "ubuntu": "debian",
    "rhel": "rhel",
    "centos": "rhel",
    "fedora": "rhel",
    "rocky": "rhel",
    "almalinux": "rhel",
}


def get_os_family():
    """
    Returns the distro family whose tooling applies: 'debian', 'rhel', or
    'unknown'.

    ID is checked first, then ID_LIKE, which is how a derivative declares whose
    conventions it follows (Rocky sets ID=rocky, ID_LIKE="rhel centos fedora").
    This is what picks apt vs dnf and ufw vs firewall-cmd; where a check can
    read the kernel directly instead, it does, and never needs this.
    """
    try:
        release = platform.freedesktop_os_release()
    except (OSError, AttributeError):
        return "unknown"

    identifier = (release.get("ID") or "").strip().lower()
    if identifier in OS_FAMILIES:
        return OS_FAMILIES[identifier]
    for token in (release.get("ID_LIKE") or "").lower().split():
        if token in OS_FAMILIES:
            return OS_FAMILIES[token]
    return "unknown"

def detect_environment():
    """
    Detects the execution environment.
    """
    if os.getenv("CI") == "true":
        return "CI"
    if os.getenv("GITHUB_ACTIONS") == "true":
        return "GitHub Actions"
    if is_docker():
        return "Docker"
    release = platform.release().lower()
    if "microsoft" in release or "wsl" in release:
        return "WSL2"
    return "Linux"

def get_system_identity(env):
    """
    Collects system identity information.
    """
    return {
        "os": platform.system(),
        "distro": (
            platform.freedesktop_os_release().get("PRETTY_NAME", "Unknown")
            if hasattr(platform, "freedesktop_os_release")
            else "Unknown"
        ),
        "kernel": platform.release(),
        "hostname": platform.node(),
        "cpu_cores": get_cpu_cores(),
        "os_family": get_os_family(),
        "environment": env
    }


def get_cpu_cores():
    """
    Returns the number of logical CPUs, via nproc with a stdlib fallback.

    nproc reports the CPUs actually available to this process (it honours
    cgroup and affinity limits), which is what matters when normalizing load.
    """
    result = run_command(["nproc"])
    if result["success"]:
        try:
            return int(result["stdout"].strip())
        except ValueError:
            pass
    return os.cpu_count()

def is_docker():
    """
    Checks if the code is running inside a container (Docker, Podman, LXC, Kubernetes).
    """
    if os.path.exists("/.dockerenv"):
        return True
    try:
        content = open("/proc/1/cgroup").read()
        if any(x in content for x in ("docker", "kubepods", "containerd", "lxc")):
            return True
    except Exception:
        pass
    return os.getenv("container", "").lower() in {"docker", "containerd", "podman"}


def get_monitored_services():
    """
    Returns the service names to check.

    Configurable because the interesting units differ per host: a Docker host
    watches docker.service, a rootless Podman host watches its Quadlet unit.
    """
    configured = os.getenv("HEALTH_SERVICES", "").strip()
    if configured:
        return [name for name in (s.strip() for s in configured.split(",")) if name]
    return DEFAULT_SERVICES


def get_service_statuses(env):
    """
    Returns key system service statuses based on the environment.
    """
    if env in ["Docker", "CI", "WSL2"]:
        return {
            "feature": "services",
            "success": False,
            "reason": f"systemctl not available in {env}",
            "data": None
        }
    return {
        "feature": "services",
        "success": True,
        "data": [get_service_status(name) for name in get_monitored_services()]
    }


def get_service_status(name):
    """
    Check the status of a specific service.

    `systemctl is-active` exits non-zero for a unit that is simply stopped, so
    its stdout ("inactive", "failed") is the answer whenever it produced one;
    an empty stdout means systemctl itself could not answer.
    """
    result = run_command(["systemctl", "is-active", name])
    status = result["stdout"].strip()
    if not status:
        return {
            "service": name,
            "status": "unknown",
            "error": result["stderr"]
        }
    return {
        "service": name,
        "status": status
    }

def _rootless_command(command, user):
    """
    Rewrites a runtime command to run inside another user's login session.

    A rootless Podman container belongs to the user that started it: root's
    `podman ps` queries root's own (empty) store and reports nothing. Entering
    the user's session with their XDG_RUNTIME_DIR set is what makes their
    containers visible from a system-wide monitor.
    """
    try:
        import pwd
        uid = pwd.getpwnam(user).pw_uid
    except (ImportError, KeyError):
        return None
    inner = " ".join(command)
    return [
        "su", "-", user, "-c",
        f"XDG_RUNTIME_DIR=/run/user/{uid} {inner}",
    ]


def get_containers():
    """
    Returns the running containers from whichever runtime is present.

    Probes Docker then Podman so the same agent works on a Docker host and a
    Podman host without configuration. Set HEALTH_CONTAINER_USER to inspect a
    rootless runtime owned by that user.
    """
    container_user = os.getenv("HEALTH_CONTAINER_USER", "").strip()
    attempted = []
    for runtime in CONTAINER_RUNTIMES:
        command = [runtime, "ps", "--format", "{{.Names}}"]
        #only step into another user's session when we are not already them
        if container_user and container_user != os.getenv("USER"):
            wrapped = _rootless_command(command, container_user)
            if wrapped:
                command = wrapped
        result = run_command(command)
        attempted.append(runtime)
        if not result["success"]:
            continue
        containers = [c for c in result["stdout"].splitlines() if c]
        return {
            "feature": "containers",
            "success": True,
            "runtime": runtime,
            "running_containers": containers,
            "count": len(containers)
        }
    return {
        "feature": "containers",
        "success": False,
        "reason": f"no container runtime available (tried: {', '.join(attempted)})",
        "data": None
    }

def get_failed_services(env):
    if env in ["Docker", "CI", "WSL2", "GitHub Actions"]:
        return {"success": False, "reason": f"systemctl not available in {env}"}
    result = run_command(["systemctl", "--failed", "--no-legend", "--plain"])
    if not result["success"]:
        return {"success": False, "reason": result["stderr"] or "systemctl unavailable"}
    failed = [line.split()[0] for line in result["stdout"].splitlines() if line.strip()]
    return {"success": True, "count": len(failed), "services": failed}


def get_listening_ports():
    """
    Returns the sockets the host is listening on, via `ss -tulnp`.

    -n keeps ports numeric (no DNS/service lookups to block on) and -p asks for
    the owning process, which the kernel only reveals to root: unprivileged
    runs still get every port, just without process names.
    """
    result = run_command(["ss", "-tulnp"])
    if not result["stdout"]:
        return {
            "feature": "listening_ports",
            "success": False,
            "reason": result["stderr"] or "ss not available",
            "data": None
        }

    ports = []
    for line in result["stdout"].splitlines():
        fields = line.split()
        #selecting on the protocol column skips the header without relying on
        #its column count ("Local Address:Port" itself contains a space)
        if len(fields) < 5 or fields[0] not in ("tcp", "udp"):
            continue
        local = fields[4]
        address, _, port = local.rpartition(":")
        if not port.isdigit():
            continue
        processes = re.findall(r'"([^"]+)"', line)
        ports.append({
            "protocol": fields[0],
            "address": address,
            "port": int(port),
            "process": processes[0] if processes else None,
        })

    ports.sort(key=lambda p: (p["port"], p["protocol"]))
    return {
        "feature": "listening_ports",
        "success": True,
        "count": len(ports),
        "data": ports
    }


def get_disk_details():
    """
    Returns details about the disk usage, including the largest files in a specified directory.
    """
    try:
        return {
            "feature": "disk_details",
            "success": True,
            "data": get_directory_usage()
        }
    except PermissionError:
        return {
            "feature": "disk_details",
            "success": False,
            "error": "permission denied",
            "data": None
        }