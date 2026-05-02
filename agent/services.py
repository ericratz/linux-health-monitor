#services.py
from agent.utils import run_command

def get_system_services(env):
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
        "data": [
            check_service_status("nginx"),
            check_service_status("docker")
        ]
    }


def check_service_status(name):
    result = run_command(["systemctl", "is-active", name])

    if not result["success"]:
        return {
            "service": name,
            "status": "unknown",
            "error": result["stderr"]
        }

    return {
        "service": name,
        "status": result["stdout"].strip()
    }

def get_docker_status():
    result = run_command(["docker", "ps", "--format", "{{.Names}}"])

    if not result["success"]:
        return {
            "feature": "docker",
            "success": False,
            "reason": "docker CLI not available in environment",
            "data": None
        }

    containers = [c for c in result["stdout"].splitlines() if c]

    return {
        "feature": "docker",
        "success": True,
        "running_containers": containers,
        "count": len(containers)
    }



