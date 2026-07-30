"""
Tests for host context collection: runtime detection, unit status and identity.
"""
from agent import system_context as sc


def _fake_run(responses):
    """
    Builds a run_command stub that answers per binary name.

    Anything not listed behaves like a missing binary, which is how a real host
    reports a runtime it does not have installed.
    """
    def runner(command, timeout=3):
        binary = command[0]
        if binary in responses:
            return responses[binary]
        return {"stdout": "", "stderr": "not found", "returncode": -1, "success": False}
    return runner


def test_containers_prefers_docker_when_present(monkeypatch):
    monkeypatch.delenv("HEALTH_CONTAINER_USER", raising=False)
    monkeypatch.setattr(sc, "run_command", _fake_run({
        "docker": {"stdout": "api\ndb", "stderr": "", "returncode": 0, "success": True},
    }))
    result = sc.get_containers()
    assert result["success"] is True
    assert result["container_runtime"] == "docker"
    assert result["running_containers"] == ["api", "db"]
    assert result["count"] == 2


def test_containers_falls_back_to_podman(monkeypatch):
    #node2 has no docker binary at all
    monkeypatch.delenv("HEALTH_CONTAINER_USER", raising=False)
    monkeypatch.setattr(sc, "run_command", _fake_run({
        "podman": {"stdout": "brp-api", "stderr": "", "returncode": 0, "success": True},
    }))
    result = sc.get_containers()
    assert result["container_runtime"] == "podman"
    assert result["running_containers"] == ["brp-api"]


def test_containers_reports_when_no_runtime_exists(monkeypatch):
    monkeypatch.delenv("HEALTH_CONTAINER_USER", raising=False)
    monkeypatch.setattr(sc, "run_command", _fake_run({}))
    result = sc.get_containers()
    assert result["success"] is False
    assert "docker" in result["reason"] and "podman" in result["reason"]
    assert result["data"] is None


def test_containers_handles_a_running_runtime_with_nothing_running(monkeypatch):
    monkeypatch.delenv("HEALTH_CONTAINER_USER", raising=False)
    monkeypatch.setattr(sc, "run_command", _fake_run({
        "docker": {"stdout": "", "stderr": "", "returncode": 0, "success": True},
    }))
    result = sc.get_containers()
    assert result["success"] is True
    assert result["count"] == 0


def test_rootless_lookup_enters_the_owning_users_session(monkeypatch):
    monkeypatch.setenv("HEALTH_CONTAINER_USER", "root")
    monkeypatch.setenv("USER", "monitor")
    seen = []

    def runner(command, timeout=3):
        seen.append(command)
        return {"stdout": "brp-api", "stderr": "", "returncode": 0, "success": True}

    monkeypatch.setattr(sc, "run_command", runner)
    result = sc.get_containers()
    assert result["success"] is True
    #root resolves via pwd, so the command must be wrapped for its session
    assert seen[0][0] == "su"
    assert "XDG_RUNTIME_DIR=/run/user/0" in seen[0][-1]


def test_rootless_wrapper_declines_an_unknown_user():
    assert sc._rootless_command(["podman", "ps"], "no-such-user-here") is None


def _systemctl_show(load_state, active_state="inactive", sub_state="dead"):
    output = (
        f"LoadState={load_state}\n"
        f"ActiveState={active_state}\n"
        f"SubState={sub_state}\n"
    )
    return lambda cmd, timeout=3: {
        "stdout": output, "stderr": "", "returncode": 0, "success": True
    }


def test_service_status_reports_stopped_units(monkeypatch):
    monkeypatch.setattr(sc, "run_command", _systemctl_show("loaded", "inactive"))
    assert sc.get_service_status("nginx") == {"service": "nginx", "status": "inactive"}


def test_service_status_reports_active_units(monkeypatch):
    monkeypatch.setattr(sc, "run_command", _systemctl_show("loaded", "active", "running"))
    assert sc.get_service_status("docker")["status"] == "active"


def test_service_status_distinguishes_not_installed_from_stopped(monkeypatch):
    #docker on a Podman host: `is-active` says "inactive", which reads as
    #"installed but stopped" and is misleading
    monkeypatch.setattr(sc, "run_command", _systemctl_show("not-found"))
    assert sc.get_service_status("docker") == {
        "service": "docker", "status": "not-installed"
    }


def test_service_status_reports_masked_units(monkeypatch):
    monkeypatch.setattr(sc, "run_command", _systemctl_show("masked"))
    assert sc.get_service_status("firewalld")["status"] == "masked"


def test_service_status_explains_a_failure(monkeypatch):
    monkeypatch.setattr(
        sc, "run_command", _systemctl_show("loaded", "failed", "exit-code")
    )
    result = sc.get_service_status("brp-api")
    assert result["status"] == "failed"
    assert result["detail"] == "exit-code"


def test_service_status_unknown_when_systemctl_cannot_answer(monkeypatch):
    monkeypatch.setattr(sc, "run_command", lambda cmd, timeout=3: {
        "stdout": "", "stderr": "bus error", "returncode": 1, "success": False
    })
    result = sc.get_service_status("nginx")
    assert result["status"] == "unknown"
    assert result["error"] == "bus error"


def test_monitored_services_are_configurable(monkeypatch):
    monkeypatch.setenv("HEALTH_SERVICES", "nginx, keepalived ,brp-api")
    assert sc.get_monitored_services() == ["nginx", "keepalived", "brp-api"]


def test_monitored_services_default_when_unset(monkeypatch):
    monkeypatch.delenv("HEALTH_SERVICES", raising=False)
    assert sc.get_monitored_services() == sc.DEFAULT_SERVICES


def test_monitored_services_ignores_blank_config(monkeypatch):
    monkeypatch.setenv("HEALTH_SERVICES", "   ")
    assert sc.get_monitored_services() == sc.DEFAULT_SERVICES


def test_services_skipped_where_systemctl_is_meaningless():
    for env in ("Docker", "CI", "WSL2"):
        result = sc.get_service_statuses(env)
        assert result["success"] is False
        assert env in result["reason"]


def test_have_detects_present_and_absent_binaries():
    from agent.shell import have
    #sh exists on any host that can run this suite
    assert have("sh") is True
    assert have("definitely-not-a-real-binary-xyz") is False


def test_have_caches_lookups(monkeypatch):
    from agent import shell
    calls = []

    def spy(name):
        calls.append(name)
        return "/usr/bin/thing"

    monkeypatch.setattr(shell.shutil, "which", spy)
    monkeypatch.setattr(shell, "_HAVE_CACHE", {})
    assert shell.have("thing") is True
    assert shell.have("thing") is True
    #PATH does not change mid-run, so the second call is served from cache
    assert calls == ["thing"]


SS_OUTPUT = """Netid State  Recv-Q Send-Q Local Address:Port  Peer Address:PortProcess
udp   UNCONN 0      0      127.0.0.53%lo:53         0.0.0.0:*
udp   UNCONN 0      0              [::1]:323           [::]:*
tcp   LISTEN 0      4096         0.0.0.0:8000         0.0.0.0:*    users:(("python3",pid=456,fd=5))
tcp   LISTEN 0      511                *:80                *:*     users:(("nginx",pid=99,fd=6),("nginx",pid=98,fd=6))
"""


def test_listening_ports_parses_ss_output(monkeypatch):
    monkeypatch.setattr(sc, "run_command", lambda cmd, timeout=3: {
        "stdout": SS_OUTPUT, "stderr": "", "returncode": 0, "success": True
    })
    result = sc.get_listening_ports()
    assert result["success"] is True
    assert result["count"] == 4
    by_port = {p["port"]: p for p in result["data"]}
    #the header line must not be mistaken for a socket
    assert set(by_port) == {53, 323, 80, 8000}
    assert by_port[8000]["process"] == "python3"
    assert by_port[8000]["protocol"] == "tcp"
    #IPv6 and scope-suffixed addresses keep their address intact
    assert by_port[323]["address"] == "[::1]"
    assert by_port[53]["address"] == "127.0.0.53%lo"
    #ports come back in a stable order
    assert [p["port"] for p in result["data"]] == [53, 80, 323, 8000]


def test_listening_ports_without_root_has_no_process_names(monkeypatch):
    #the kernel hides socket ownership from unprivileged callers
    unprivileged = (
        "Netid State  Recv-Q Send-Q Local Address:Port Peer Address:Port\n"
        "tcp   LISTEN 0      4096         0.0.0.0:8000       0.0.0.0:*\n"
    )
    monkeypatch.setattr(sc, "run_command", lambda cmd, timeout=3: {
        "stdout": unprivileged, "stderr": "", "returncode": 0, "success": True
    })
    result = sc.get_listening_ports()
    assert result["data"][0]["port"] == 8000
    assert result["data"][0]["process"] is None


def test_listening_ports_degrades_when_ss_missing(monkeypatch):
    monkeypatch.setattr(sc, "run_command", lambda cmd, timeout=3: {
        "stdout": "", "stderr": "ss: command not found", "returncode": -1,
        "success": False
    })
    result = sc.get_listening_ports()
    assert result["success"] is False
    assert result["data"] is None
    assert "not found" in result["reason"]


def test_cpu_cores_uses_nproc(monkeypatch):
    monkeypatch.setattr(sc, "run_command", lambda cmd, timeout=3: {
        "stdout": "4", "stderr": "", "returncode": 0, "success": True
    })
    assert sc.get_cpu_cores() == 4


def test_cpu_cores_falls_back_when_nproc_absent(monkeypatch):
    monkeypatch.setattr(sc, "run_command", lambda cmd, timeout=3: {
        "stdout": "", "stderr": "not found", "returncode": -1, "success": False
    })
    assert sc.get_cpu_cores() == sc.os.cpu_count()


def test_cpu_cores_falls_back_on_unparseable_output(monkeypatch):
    monkeypatch.setattr(sc, "run_command", lambda cmd, timeout=3: {
        "stdout": "lots", "stderr": "", "returncode": 0, "success": True
    })
    assert sc.get_cpu_cores() == sc.os.cpu_count()


def test_system_identity_shape():
    identity = sc.get_system_identity(sc.detect_environment())
    assert set(identity) == {
        "os", "distro", "kernel", "hostname", "cpu_cores", "os_family",
        "environment",
    }
    assert isinstance(identity["cpu_cores"], int)


def test_os_family_from_id(monkeypatch):
    monkeypatch.setattr(
        sc.platform, "freedesktop_os_release", lambda: {"ID": "rocky"}
    )
    assert sc.get_os_family() == "rhel"


def test_os_family_falls_back_to_id_like(monkeypatch):
    #a derivative declares whose conventions it follows via ID_LIKE
    monkeypatch.setattr(
        sc.platform, "freedesktop_os_release",
        lambda: {"ID": "somethingnew", "ID_LIKE": "rhel centos fedora"},
    )
    assert sc.get_os_family() == "rhel"
    monkeypatch.setattr(
        sc.platform, "freedesktop_os_release",
        lambda: {"ID": "ubuntu", "ID_LIKE": "debian"},
    )
    assert sc.get_os_family() == "debian"


def test_os_family_unknown_for_unrecognized_and_missing(monkeypatch):
    monkeypatch.setattr(
        sc.platform, "freedesktop_os_release", lambda: {"ID": "plan9"}
    )
    assert sc.get_os_family() == "unknown"

    def raise_os_error():
        raise OSError("no os-release")

    monkeypatch.setattr(sc.platform, "freedesktop_os_release", raise_os_error)
    assert sc.get_os_family() == "unknown"


def test_os_family_on_this_host_is_debian_or_rhel():
    #this box is Debian family; the value must never be a raw distro name
    assert sc.get_os_family() in {"debian", "rhel", "unknown"}
