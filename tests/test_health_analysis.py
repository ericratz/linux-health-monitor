"""
Tests for threshold evaluation, diagnosis and recommendations.

The central property: status, alerts, diagnosis and actions must agree. A host
with a dead service must not report "No issues detected" while the action list
names four problems.
"""
from agent.health_analysis import (
    generate_alerts,
    generate_diagnostics,
    generate_health_status,
    generate_recommendations,
)

HEALTHY = {"cpu": 5, "mem_used": 20, "disk_used": 10, "load": {"1min": 0.1}}


def test_healthy_host_is_quiet():
    assert generate_health_status(HEALTHY) == "HEALTHY"
    assert generate_alerts(HEALTHY) == []
    assert generate_diagnostics(HEALTHY) == ["No issues detected"]
    assert generate_recommendations(HEALTHY, "Linux", "debian") == []


def test_full_non_root_filesystem_is_critical():
    #the gap this closes: / looks fine while /var is the one filling up
    ctx = {**HEALTHY, "filesystems": [
        {"mount": "/", "used_percent": 10.0},
        {"mount": "/var", "used_percent": 95.0},
    ]}
    assert generate_health_status(ctx) == "CRITICAL"
    assert any("/var" in alert for alert in generate_alerts(ctx))
    assert any("/var" in note for note in generate_diagnostics(ctx))
    #du is scoped with -x so it cannot wander onto another filesystem
    actions = generate_recommendations(ctx, "Linux", "debian")
    assert any("du -xh" in action and "/var" in action for action in actions)


def test_root_filesystem_is_not_double_reported():
    ctx = {**HEALTHY, "disk_used": 95.0, "filesystems": [
        {"mount": "/", "used_percent": 95.0},
    ]}
    alerts = generate_alerts(ctx)
    #"High disk usage" covers root; a second mount-specific alert would repeat it
    assert alerts.count("High disk usage") == 1
    assert not any("on /" in alert for alert in alerts)


def test_filesystem_below_threshold_is_silent():
    ctx = {**HEALTHY, "filesystems": [{"mount": "/var", "used_percent": 50.0}]}
    assert generate_health_status(ctx) == "HEALTHY"
    assert generate_alerts(ctx) == []


def test_high_iowait_diagnoses_disk_bound_not_cpu_bound():
    ctx = {**HEALTHY, "cpu": 4, "load": {"1min": 8.0},
           "pressure": {"iowait_percent": 62.5},
           "processes": {"blocked": 7}}
    diagnosis = " ".join(generate_diagnostics(ctx))
    assert "disk-bound" in diagnosis
    assert "7 process" in diagnosis
    #the old load-vs-cpu guess must not also fire
    assert "possible I/O wait" not in diagnosis
    actions = generate_recommendations(ctx, "Linux", "debian")
    #a dependency-free way to find the blocked processes
    assert any("awk" in action for action in actions)


def test_low_iowait_falls_back_to_the_load_heuristic():
    ctx = {**HEALTHY, "cpu": 1, "load": {"1min": 4.0},
           "pressure": {"iowait_percent": 0.5}}
    assert any("possible I/O wait" in note for note in generate_diagnostics(ctx))


def test_swapping_out_is_diagnosed_as_memory_pressure():
    ctx = {**HEALTHY, "pressure": {"swap_out_bytes_per_sec": 4194304}}
    assert "Swapping out to disk" in generate_alerts(ctx)
    assert any("memory pressure" in note for note in generate_diagnostics(ctx))


def test_missing_pressure_data_is_not_an_error():
    #an older collector or a container may supply nothing
    ctx = {**HEALTHY, "pressure": {"iowait_percent": None}}
    assert generate_health_status(ctx) == "HEALTHY"
    assert generate_alerts(ctx) == []


def test_failed_unit_makes_an_idle_host_a_warning():
    ctx = {**HEALTHY, "failed_services": 2}
    assert generate_health_status(ctx) == "WARNING"
    assert any("failed" in alert for alert in generate_alerts(ctx))
    assert any("failed" in note for note in generate_diagnostics(ctx))
    assert "Run: systemctl --failed" in generate_recommendations(ctx, "Linux", "rhel")


def test_clock_skew_is_a_warning():
    ctx = {**HEALTHY, "time_desynchronized": True}
    assert generate_health_status(ctx) == "WARNING"
    assert any("Clock" in note for note in generate_diagnostics(ctx))


def test_journal_errors_reach_diagnosis_without_gating_exit_code():
    ctx = {**HEALTHY, "journal_errors": {
        "count": 41, "window": "-1h",
        "by_unit": [{"unit": "nginx.service", "count": 30}],
    }}
    #error volume is too noisy to drive an exit code, but must still be visible
    assert generate_health_status(ctx) == "HEALTHY"
    assert any("41" in alert for alert in generate_alerts(ctx))
    assert any("nginx.service" in note for note in generate_diagnostics(ctx))
    actions = generate_recommendations(ctx, "Linux", "debian")
    assert "Run: journalctl -u nginx.service -p err --since -1h" in actions


def test_kernel_errors_do_not_produce_a_unit_command():
    ctx = {**HEALTHY, "journal_errors": {
        "count": 3, "window": "-1h", "by_unit": [{"unit": "kernel", "count": 3}],
    }}
    actions = generate_recommendations(ctx, "Linux", "debian")
    assert not any("journalctl -u kernel" in action for action in actions)


def test_reboot_recommendation_is_family_correct():
    ctx = {**HEALTHY, "reboot_required": True}
    debian = generate_recommendations(ctx, "Linux", "debian")
    rhel = generate_recommendations(ctx, "Linux", "rhel")
    assert any("reboot-required.pkgs" in action for action in debian)
    assert any("needs-restarting" in action for action in rhel)
    #a pending reboot is worth saying, but is not a health failure
    assert generate_health_status(ctx) == "HEALTHY"


def test_generic_log_hint_is_dropped_when_a_unit_was_named():
    named = {**HEALTHY, "journal_errors": {
        "count": 1, "window": "-1h", "by_unit": [{"unit": "sshd.service", "count": 1}],
    }}
    actions = generate_recommendations(named, "Linux", "debian")
    assert not any("<service>" in action for action in actions)


def test_generic_log_hint_appears_when_nothing_specific_is_known():
    ctx = {**HEALTHY, "cpu": 99}
    actions = generate_recommendations(ctx, "Linux", "debian")
    assert any("<service>" in action for action in actions)


def test_no_log_hint_inside_a_container():
    ctx = {**HEALTHY, "cpu": 99}
    for env in ("Docker", "CI", "GitHub Actions"):
        actions = generate_recommendations(ctx, env, "debian")
        assert not any("journalctl" in action for action in actions)


def test_thresholds_remain_env_configurable(monkeypatch):
    monkeypatch.setenv("HEALTH_DISK_CRIT", "5")
    ctx = {**HEALTHY, "filesystems": [{"mount": "/data", "used_percent": 10.0}]}
    assert generate_health_status(ctx) == "CRITICAL"


def test_status_and_diagnosis_never_disagree():
    #the coherence property, checked across a spread of unhealthy contexts
    contexts = [
        {**HEALTHY, "failed_services": 1},
        {**HEALTHY, "time_desynchronized": True},
        {**HEALTHY, "cpu": 99},
        {**HEALTHY, "mem_used": 99},
        {**HEALTHY, "filesystems": [{"mount": "/var", "used_percent": 99.0}]},
    ]
    for ctx in contexts:
        assert generate_health_status(ctx) != "HEALTHY"
        assert generate_diagnostics(ctx) != ["No issues detected"]
        assert generate_alerts(ctx)
