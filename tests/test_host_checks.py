"""
Tests for host posture checks.

Each check has to work on a minimized install of either distro family, so the
degradation paths (missing binary, missing kernel interface, unreadable
root-only file) matter as much as the happy path.
"""
import json

from agent import host_checks as hc


def _journal_output(entries):
    """Builds journalctl --output=json output: one JSON object per line."""
    return "\n".join(json.dumps(entry) for entry in entries)


def _stub(hc_module, monkeypatch, *, available=True, stdout="", stderr="",
          returncode=0):
    monkeypatch.setattr(hc_module, "have", lambda cmd: available)
    monkeypatch.setattr(hc_module, "run_command", lambda cmd, timeout=3: {
        "stdout": stdout, "stderr": stderr, "returncode": returncode,
        "success": returncode == 0,
    })


def test_journal_errors_counts_entries_not_lines(monkeypatch):
    #a multi-line message is ONE entry; counting lines would overcount it
    entries = [
        {"MESSAGE": "line one\nline two\nline three", "_SYSTEMD_UNIT": "nginx.service"},
        {"MESSAGE": "single", "_SYSTEMD_UNIT": "nginx.service"},
        {"MESSAGE": "kernel oops"},
    ]
    _stub(hc, monkeypatch, stdout=_journal_output(entries))
    result = hc.get_journal_errors()
    assert result["success"] is True
    assert result["count"] == 3
    assert result["by_unit"][0] == {"unit": "nginx.service", "count": 2}
    #an entry with no unit is attributed to the kernel
    assert {"unit": "kernel", "count": 1} in result["by_unit"]


def test_journal_errors_truncates_long_messages(monkeypatch):
    entries = [{"MESSAGE": "x" * 5000, "_SYSTEMD_UNIT": "a.service"}]
    _stub(hc, monkeypatch, stdout=_journal_output(entries))
    result = hc.get_journal_errors()
    assert len(result["data"][0]["message"]) == hc.JOURNAL_MESSAGE_CHARS


def test_journal_errors_skips_binary_messages(monkeypatch):
    #journald renders a non-UTF8 message as a list of byte values
    entries = [{"MESSAGE": [104, 105], "_SYSTEMD_UNIT": "a.service"}]
    _stub(hc, monkeypatch, stdout=_journal_output(entries))
    result = hc.get_journal_errors()
    #still counted, but not offered as a readable sample
    assert result["count"] == 1
    assert result["data"] == []


def test_journal_errors_clean_host(monkeypatch):
    _stub(hc, monkeypatch, stdout="")
    result = hc.get_journal_errors()
    assert result["success"] is True
    assert result["count"] == 0
    assert result["by_unit"] == []


def test_journal_errors_ignores_unparseable_lines(monkeypatch):
    _stub(hc, monkeypatch, stdout='{"MESSAGE": "ok"}\nnot json at all\n')
    assert hc.get_journal_errors()["count"] == 1


def test_journal_errors_window_is_configurable(monkeypatch):
    seen = {}

    monkeypatch.setattr(hc, "have", lambda cmd: True)

    def runner(command, timeout=3):
        seen["command"] = command
        return {"stdout": "", "stderr": "", "returncode": 0, "success": True}

    monkeypatch.setattr(hc, "run_command", runner)
    monkeypatch.setenv(hc.JOURNAL_WINDOW_ENV, "-30m")
    assert hc.get_journal_errors()["window"] == "-30m"
    assert "--since=-30m" in seen["command"]


def test_journal_errors_degrades_without_journalctl(monkeypatch):
    _stub(hc, monkeypatch, available=False)
    result = hc.get_journal_errors()
    assert result["success"] is False
    assert "journalctl" in result["reason"]


def test_time_sync_reports_synchronized(monkeypatch):
    monkeypatch.setattr(hc, "have", lambda cmd: True)
    monkeypatch.setattr(hc, "_timedatectl_properties", lambda: {
        "NTPSynchronized": "yes", "NTP": "yes", "Timezone": "UTC"
    })
    monkeypatch.setattr(hc, "_active_unit", lambda units: ("chronyd", {}))
    result = hc.get_time_sync()
    assert result["synchronized"] is True
    assert result["ntp_enabled"] is True
    assert result["timezone"] == "UTC"
    #the daemon is detected, not assumed per family: chrony is common on both
    assert result["service"] == "chronyd"


def test_time_sync_reports_skew(monkeypatch):
    monkeypatch.setattr(hc, "have", lambda cmd: True)
    monkeypatch.setattr(hc, "_timedatectl_properties", lambda: {
        "NTPSynchronized": "no", "NTP": "yes"
    })
    monkeypatch.setattr(hc, "_active_unit", lambda units: (None, {}))
    result = hc.get_time_sync()
    assert result["synchronized"] is False
    assert result["service"] is None


def test_time_sync_degrades_without_timedatectl(monkeypatch):
    _stub(hc, monkeypatch, available=False)
    assert hc.get_time_sync()["success"] is False


def test_selinux_enforcing_read_from_sysfs(monkeypatch):
    #getenforce is a separate package; the kernel file is always there
    monkeypatch.setattr(hc, "_read_file", lambda path: "1" if "enforce" in path else None)
    result = hc.get_security_module()
    assert result["module"] == "selinux"
    assert result["mode"] == "enforcing"


def test_selinux_permissive(monkeypatch):
    monkeypatch.setattr(hc, "_read_file", lambda path: "0" if "enforce" in path else None)
    assert hc.get_security_module()["mode"] == "permissive"


def test_apparmor_enabled_with_profile_count(monkeypatch):
    def read(path):
        if "apparmor/parameters/enabled" in path:
            return "Y\n"
        if "apparmor/profiles" in path:
            return "profile_a (enforce)\nprofile_b (complain)\n"
        return None

    monkeypatch.setattr(hc, "_read_file", read)
    result = hc.get_security_module()
    assert result["module"] == "apparmor"
    assert result["mode"] == "enforcing"
    assert result["profiles_loaded"] == 2


def test_apparmor_without_readable_profiles(monkeypatch):
    #the profiles list is root-only; absence must not be an error
    monkeypatch.setattr(
        hc, "_read_file",
        lambda path: "Y" if "parameters/enabled" in path else None,
    )
    result = hc.get_security_module()
    assert result["mode"] == "enforcing"
    assert result["profiles_loaded"] is None


def test_apparmor_disabled(monkeypatch):
    monkeypatch.setattr(
        hc, "_read_file",
        lambda path: "N" if "parameters/enabled" in path else None,
    )
    assert hc.get_security_module()["mode"] == "disabled"


def test_selinuxfs_mounted_but_policy_not_loaded(monkeypatch):
    monkeypatch.setattr(hc, "_read_file", lambda path: None)
    monkeypatch.setattr(hc.os.path, "isdir", lambda path: path == hc.SELINUX_ROOT)
    result = hc.get_security_module()
    assert result["module"] == "selinux"
    assert result["mode"] == "disabled"


def test_no_security_module_present(monkeypatch):
    monkeypatch.setattr(hc, "_read_file", lambda path: None)
    monkeypatch.setattr(hc.os.path, "isdir", lambda path: False)
    result = hc.get_security_module()
    assert result["success"] is False
    assert "SELinux" in result["reason"]


def test_firewall_reports_active_unit(monkeypatch):
    monkeypatch.setattr(hc, "have", lambda cmd: cmd == "systemctl")
    monkeypatch.setattr(hc, "_active_unit", lambda units: (
        "firewalld", {"firewalld": "active", "ufw": "inactive"}
    ))
    result = hc.get_firewall()
    assert result["active"] == "firewalld"
    #firewall-cmd absent, so no enrichment was attempted
    assert result["detail"] is None
    assert {"unit": "firewalld", "state": "active"} in result["data"]


def test_firewall_enriches_when_cli_present(monkeypatch):
    monkeypatch.setattr(hc, "have", lambda cmd: True)
    monkeypatch.setattr(hc, "_active_unit", lambda units: ("firewalld", {}))
    monkeypatch.setattr(hc, "run_command", lambda cmd, timeout=3: {
        "stdout": "public", "stderr": "", "returncode": 0, "success": True
    })
    assert "public" in hc.get_firewall()["detail"]


def test_firewall_none_active_is_a_finding_not_an_error(monkeypatch):
    monkeypatch.setattr(hc, "have", lambda cmd: cmd == "systemctl")
    monkeypatch.setattr(hc, "_active_unit", lambda units: (
        None, {unit: "inactive" for unit in hc.FIREWALL_UNITS}
    ))
    result = hc.get_firewall()
    assert result["success"] is True
    assert result["active"] is None


#one address per line, which is what `ip -o addr show` produces
IP_ADDR_OUTPUT = (
    "1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever\n"
    "2: eth0    inet 192.168.71.251/24 brd 192.168.71.255 scope global eth0\\"
    "       valid_lft forever\n"
    "2: eth0    inet 192.168.71.250/32 scope global eth0\\       valid_lft forever\n"
    "2: eth0    inet6 fe80::1/64 scope link \\       valid_lft forever\n"
)


def test_vip_reports_the_holder(monkeypatch):
    monkeypatch.setenv(hc.VIP_ENV, "192.168.71.250")
    _stub(hc, monkeypatch, stdout=IP_ADDR_OUTPUT)
    result = hc.get_vip_status()
    assert result["holds_vip"] is True
    assert result["held_count"] == 1
    assert result["data"][0] == {
        "address": "192.168.71.250", "held": True, "interface": "eth0"
    }


def test_vip_absent_is_the_backup_nodes_normal_state(monkeypatch):
    monkeypatch.setenv(hc.VIP_ENV, "192.168.71.250")
    #the peer holds it: this host has only its own address
    _stub(hc, monkeypatch, stdout="2: eth0    inet 192.168.71.252/24 scope global eth0")
    result = hc.get_vip_status()
    #success: the check answered. holds_vip False is data, not a failure
    assert result["success"] is True
    assert result["holds_vip"] is False
    assert result["data"][0]["interface"] is None


def test_vip_not_held_names_whoever_is_answering(monkeypatch):
    #the case an HTTP check cannot see: the VIP answers fine, but the responder
    #is an unrelated device, so claiming the address would collide with it
    monkeypatch.setattr(hc, "have", lambda cmd: True)

    def runner(command, timeout=3):
        if command[1] == "neigh":
            out = "192.168.71.250 dev enp1s0 lladdr d8:44:89:a0:66:60 STALE"
        else:
            out = "2: enp1s0    inet 192.168.71.251/22 scope global enp1s0"
        return {"stdout": out, "stderr": "", "returncode": 0, "success": True}

    monkeypatch.setattr(hc, "run_command", runner)
    monkeypatch.setenv(hc.VIP_ENV, "192.168.71.250")
    entry = hc.get_vip_status()["data"][0]
    assert entry["held"] is False
    assert entry["answered_by"] == "d8:44:89:a0:66:60"


def test_vip_not_held_and_nothing_answering(monkeypatch):
    monkeypatch.setenv(hc.VIP_ENV, "10.0.0.9")
    _stub(hc, monkeypatch, stdout="2: eth0    inet 192.168.71.252/24 scope global eth0")
    #an empty neighbour cache is not an error: nobody has the address
    assert hc.get_vip_status()["data"][0]["answered_by"] is None


def test_vip_held_does_not_probe_the_neighbour_cache(monkeypatch):
    monkeypatch.setenv(hc.VIP_ENV, "192.168.71.250")
    _stub(hc, monkeypatch, stdout="2: eth0    inet 192.168.71.250/32 scope global eth0")
    entry = hc.get_vip_status()["data"][0]
    assert entry["held"] is True
    assert "answered_by" not in entry


def test_vip_accepts_several_addresses(monkeypatch):
    monkeypatch.setenv(hc.VIP_ENV, "192.168.71.250, 10.0.0.9")
    _stub(hc, monkeypatch, stdout=IP_ADDR_OUTPUT)
    result = hc.get_vip_status()
    assert [entry["held"] for entry in result["data"]] == [True, False]
    assert result["held_count"] == 1


def test_vip_unconfigured_is_omitted_not_failed(monkeypatch):
    monkeypatch.delenv(hc.VIP_ENV, raising=False)
    result = hc.get_vip_status()
    assert result["success"] is False
    assert hc.VIP_ENV in result["reason"]


def test_vip_degrades_without_ip_command(monkeypatch):
    monkeypatch.setenv(hc.VIP_ENV, "192.168.71.250")
    _stub(hc, monkeypatch, available=False)
    assert hc.get_vip_status()["success"] is False


def test_reboot_required_debian_flag_file(monkeypatch):
    monkeypatch.setattr(hc.os.path, "exists", lambda path: path == hc.DEBIAN_REBOOT_FLAG)
    monkeypatch.setattr(hc, "_read_file", lambda path: "linux-image-generic\nlibc6\n")
    result = hc.get_reboot_required("debian")
    assert result["reboot_required"] is True
    assert result["data"] == ["libc6", "linux-image-generic"]


def test_reboot_not_required_on_debian(monkeypatch):
    monkeypatch.setattr(hc.os.path, "exists", lambda path: False)
    result = hc.get_reboot_required("debian")
    assert result["success"] is True
    assert result["reboot_required"] is False


def test_reboot_required_rhel_via_dnf(monkeypatch):
    monkeypatch.setattr(hc.os.path, "exists", lambda path: False)
    monkeypatch.setattr(hc, "have", lambda cmd: cmd == "dnf")
    #exit 1 from needs-restarting --reboothint means a reboot is needed
    monkeypatch.setattr(hc, "run_command", lambda cmd, timeout=3: {
        "stdout": "", "stderr": "", "returncode": 1, "success": False
    })
    result = hc.get_reboot_required("rhel")
    assert result["success"] is True
    assert result["reboot_required"] is True


def test_reboot_not_required_rhel(monkeypatch):
    monkeypatch.setattr(hc.os.path, "exists", lambda path: False)
    monkeypatch.setattr(hc, "have", lambda cmd: cmd == "dnf")
    monkeypatch.setattr(hc, "run_command", lambda cmd, timeout=3: {
        "stdout": "", "stderr": "", "returncode": 0, "success": True
    })
    assert hc.get_reboot_required("rhel")["reboot_required"] is False


def test_reboot_required_degrades_without_indicator(monkeypatch):
    monkeypatch.setattr(hc.os.path, "exists", lambda path: False)
    monkeypatch.setattr(hc, "have", lambda cmd: False)
    result = hc.get_reboot_required("unknown")
    assert result["success"] is False


def test_live_checks_return_declared_shapes():
    #exercises the real host: each must answer, degraded or not
    for check in (hc.get_journal_errors, hc.get_time_sync,
                  hc.get_security_module, hc.get_firewall, hc.get_vip_status):
        result = check()
        assert result["feature"]
        assert isinstance(result["success"], bool)
        if not result["success"]:
            assert result["reason"]
    reboot = hc.get_reboot_required("debian")
    assert isinstance(reboot["success"], bool)
