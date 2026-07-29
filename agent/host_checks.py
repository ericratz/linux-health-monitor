#host_checks.py
"""
Host posture checks: logs, time sync, mandatory access control, firewall and
pending reboots.

These are the checks whose tooling differs most between distro families, so
each one prefers the interface both families share:

- journald instead of /var/log/syslog vs /var/log/messages (a minimized RHEL
  host may have neither file, and journalctl is present wherever systemd is)
- /sys/fs/selinux and /sys/module/apparmor instead of getenforce and aa-status,
  which are separate packages that minimized installs omit
- systemctl unit state instead of each firewall's own CLI

Family-specific commands are used only where nothing shared exists, and every
check reports a reason instead of raising when its source is unavailable.
"""
import json
import os

from agent.shell import have, run_command

#How far back to count journal errors, in journalctl --since syntax.
JOURNAL_WINDOW_ENV = "HEALTH_JOURNAL_WINDOW"
DEFAULT_JOURNAL_WINDOW = "-1h"

#Bounds the work and the memory a noisy journal can cost us.
JOURNAL_ENTRY_CAP = 1000
JOURNAL_SAMPLE_SIZE = 5
JOURNAL_MESSAGE_CHARS = 300

#Probed in order; the first active unit is reported as the active firewall.
FIREWALL_UNITS = ("firewalld", "ufw", "nftables", "iptables")

#Time daemons, probed in order.
TIME_SERVICES = ("systemd-timesyncd", "chronyd", "chrony", "ntpd", "ntpsec")

SELINUX_ROOT = "/sys/fs/selinux"
APPARMOR_ENABLED = "/sys/module/apparmor/parameters/enabled"
APPARMOR_PROFILES = "/sys/kernel/security/apparmor/profiles"
DEBIAN_REBOOT_FLAG = "/var/run/reboot-required"
DEBIAN_REBOOT_PACKAGES = "/var/run/reboot-required.pkgs"


def _read_file(path):
    """
    Reads a file, returning None if it is missing or unreadable.
    """
    try:
        with open(path) as f:
            return f.read()
    except (OSError, ValueError):
        return None


def _unavailable(feature, reason):
    return {"feature": feature, "success": False, "reason": reason, "data": None}


def get_journal_errors():
    """
    Counts error-priority journal entries in the recent past, by unit.

    Entries are counted from JSON output rather than by counting lines: a
    multi-line message is one entry but many lines, which inflates a naive
    `journalctl | wc -l` several-fold.

    Reading the *system* journal requires membership in the journal group
    (adm on Debian, systemd-journal on RHEL) or root; an unprivileged run sees
    only the user journal and will report a smaller count.
    """
    if not have("journalctl"):
        return _unavailable("journal_errors", "journalctl not available")

    window = os.getenv(JOURNAL_WINDOW_ENV, DEFAULT_JOURNAL_WINDOW).strip() or \
        DEFAULT_JOURNAL_WINDOW
    result = run_command([
        "journalctl",
        "--priority=err",
        f"--since={window}",
        "--no-pager",
        "--quiet",
        "--output=json",
        "--output-fields=MESSAGE,_SYSTEMD_UNIT",
        f"--lines={JOURNAL_ENTRY_CAP}",
    ], timeout=15)

    if not result["success"] and not result["stdout"]:
        return _unavailable(
            "journal_errors", result["stderr"] or "journalctl returned no output"
        )

    by_unit = {}
    samples = []
    count = 0
    for line in result["stdout"].splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        count += 1
        unit = entry.get("_SYSTEMD_UNIT") or "kernel"
        by_unit[unit] = by_unit.get(unit, 0) + 1
        message = entry.get("MESSAGE")
        #a binary message decodes to a list of byte values, not a string
        if isinstance(message, str) and len(samples) < JOURNAL_SAMPLE_SIZE:
            samples.append({
                "unit": unit,
                "message": message[:JOURNAL_MESSAGE_CHARS],
            })

    top_units = sorted(by_unit.items(), key=lambda item: item[1], reverse=True)
    return {
        "feature": "journal_errors",
        "success": True,
        "window": window,
        "count": count,
        #at the cap the real total is higher; the sample is the most recent
        "capped": count >= JOURNAL_ENTRY_CAP,
        "by_unit": [{"unit": unit, "count": n} for unit, n in top_units[:5]],
        "data": samples,
    }


def _timedatectl_properties():
    """
    Returns `timedatectl show` as a dict of property -> value.
    """
    result = run_command(["timedatectl", "show"])
    if not result["stdout"]:
        return None
    properties = {}
    for line in result["stdout"].splitlines():
        key, sep, value = line.partition("=")
        if sep:
            properties[key.strip()] = value.strip()
    return properties


def _active_unit(candidates):
    """
    Returns the first unit reporting active, and the state of each probed.

    `systemctl is-active` answers "inactive" for a unit that is not installed
    at all, so absence and stopped are indistinguishable here; the states are
    returned so a reader can see what was actually probed.
    """
    states = {}
    active = None
    for unit in candidates:
        state = run_command(["systemctl", "is-active", unit])["stdout"].strip()
        states[unit] = state or "unknown"
        if state == "active" and active is None:
            active = unit
    return active, states


def get_time_sync():
    """
    Reports whether the clock is synchronized, and by which daemon.

    Clock skew between HA peers breaks certificate validation and makes
    correlating logs across nodes unreliable, so this is a health signal rather
    than trivia. `timedatectl show` is used because it answers the same way
    whether chrony, ntpd or systemd-timesyncd owns the clock;
    `timedatectl show-timesync` only works for systemd-timesyncd.
    """
    if not have("timedatectl"):
        return _unavailable("time_sync", "timedatectl not available")

    properties = _timedatectl_properties()
    if not properties:
        return _unavailable("time_sync", "timedatectl returned no output")

    service = None
    if have("systemctl"):
        service, _ = _active_unit(TIME_SERVICES)

    return {
        "feature": "time_sync",
        "success": True,
        "synchronized": properties.get("NTPSynchronized") == "yes",
        "ntp_enabled": properties.get("NTP") == "yes",
        "timezone": properties.get("Timezone"),
        "service": service,
        "data": None,
    }


def get_security_module():
    """
    Reports the active mandatory access control module and its mode.

    Read straight from the kernel rather than via getenforce/aa-status, which
    live in packages a minimized install omits. This is the usual reason a
    container or port that works on a Debian host fails on a RHEL one, so the
    mode matters when comparing two nodes.
    """
    enforce = _read_file(f"{SELINUX_ROOT}/enforce")
    if enforce is not None:
        #1 enforcing, 0 permissive
        mode = "enforcing" if enforce.strip() == "1" else "permissive"
        return {
            "feature": "security_module",
            "success": True,
            "module": "selinux",
            "mode": mode,
            "profiles_loaded": None,
            "data": None,
        }

    apparmor = _read_file(APPARMOR_ENABLED)
    if apparmor is not None:
        enabled = apparmor.strip().upper() == "Y"
        profiles = _read_file(APPARMOR_PROFILES)
        return {
            "feature": "security_module",
            "success": True,
            "module": "apparmor",
            "mode": "enforcing" if enabled else "disabled",
            #the profile list is root-only; absence is not an error
            "profiles_loaded": len(profiles.splitlines()) if profiles else None,
            "data": None,
        }

    #selinuxfs mounted but empty means the policy was never loaded
    if os.path.isdir(SELINUX_ROOT):
        return {
            "feature": "security_module",
            "success": True,
            "module": "selinux",
            "mode": "disabled",
            "profiles_loaded": None,
            "data": None,
        }

    return _unavailable("security_module", "no SELinux or AppArmor interface present")


def get_firewall():
    """
    Reports which firewall is running, without needing its CLI.

    Unit state comes from systemd, which is the same on both families; the
    family-specific CLI is only consulted for extra detail when it happens to
    be installed. A host with no active firewall is a finding, not an error.
    """
    if not have("systemctl"):
        return _unavailable("firewall", "systemctl not available")

    active, states = _active_unit(FIREWALL_UNITS)

    detail = None
    if active == "firewalld" and have("firewall-cmd"):
        #unprivileged-safe, unlike `ufw status`
        zone = run_command(["firewall-cmd", "--get-default-zone"])
        if zone["success"]:
            detail = f"default zone: {zone['stdout'].strip()}"

    return {
        "feature": "firewall",
        "success": True,
        "active": active,
        "detail": detail,
        "data": [{"unit": unit, "state": state} for unit, state in states.items()],
    }


def get_reboot_required(os_family):
    """
    Reports whether the host is waiting on a reboot.

    The two families expose this completely differently: Debian drops a flag
    file, while RHEL answers through a dnf plugin that a minimized install may
    not have. There is no shared interface, so this is real family dispatch.
    """
    if os.path.exists(DEBIAN_REBOOT_FLAG):
        packages = _read_file(DEBIAN_REBOOT_PACKAGES) or ""
        return {
            "feature": "reboot_required",
            "success": True,
            "reboot_required": True,
            "data": sorted(set(packages.split())),
        }

    if os_family == "debian":
        #the flag file's absence is a definitive "no" on this family
        return {
            "feature": "reboot_required",
            "success": True,
            "reboot_required": False,
            "data": None,
        }

    if have("dnf"):
        #exit 1 means a reboot is needed, 0 means it is not
        result = run_command(["dnf", "needs-restarting", "--reboothint"], timeout=30)
        if result["returncode"] in (0, 1):
            return {
                "feature": "reboot_required",
                "success": True,
                "reboot_required": result["returncode"] == 1,
                "data": None,
            }
        return _unavailable(
            "reboot_required",
            result["stderr"] or "dnf needs-restarting unavailable (install dnf-utils)",
        )

    return _unavailable("reboot_required", "no reboot indicator for this host")
