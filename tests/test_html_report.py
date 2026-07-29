"""
Tests for report rendering, with emphasis on escaping.

The report is intended to be served over HTTP, and every value in it is
untrusted: process names come from the kernel, unit and container names from
the host, and app-check fields from whatever a remote endpoint returned.
"""
from agent.html_report import (
    esc,
    generate_html,
    render_app_checks,
    render_containers,
    render_disk_details,
    render_failed_services,
    render_services,
)

INJECTION = '<script>alert("xss")</script>'


def test_esc_neutralizes_markup_and_quotes():
    assert "<" not in esc(INJECTION)
    assert esc('"') == "&quot;"


def test_process_names_are_escaped_into_the_document():
    #comm is attacker-controllable: a process can rename itself
    data = {
        "system": {"hostname": "node1"},
        "core_metrics": {"cpu": 1.0},
        "top_processes": [
            {"pid": 1, "name": INJECTION, "cpu_percent": 1.0, "memory_percent": 1.0}
        ],
        "health": {"status": "HEALTHY", "diagnosis": []},
    }
    html = generate_html(data)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_container_names_are_escaped():
    html = render_containers({
        "success": True, "runtime": "podman", "running_containers": [INJECTION]
    })
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_service_names_are_escaped():
    html = render_services({
        "success": True, "data": [{"service": INJECTION, "status": "active"}]
    })
    assert "<script>" not in html


def test_failed_service_names_are_escaped():
    html = render_failed_services({
        "success": True, "count": 1, "services": [INJECTION]
    })
    assert "<script>" not in html


def test_disk_detail_names_are_escaped():
    #a filename in /var/log is arbitrary user-controlled text
    html = render_disk_details({
        "success": True, "data": [{"name": INJECTION, "size_bytes": "1 KB"}]
    })
    assert "<script>" not in html


def test_app_check_fields_from_a_remote_endpoint_are_escaped():
    html = render_app_checks({
        "success": True, "count": 1, "healthy": 0,
        "data": [{
            "name": INJECTION, "url": "http://x", "success": True,
            "http_status": 200, "latency_ms": 1.0,
            "data": {"status": INJECTION},
        }],
    })
    assert "<script>" not in html
    assert html.count("&lt;script&gt;") == 2


def test_connection_error_text_stays_visible():
    #'<urlopen error ...>' would be swallowed as an unknown tag unescaped,
    #hiding the very reason an operator needs to see
    html = render_app_checks({
        "success": True, "count": 1, "healthy": 0,
        "data": [{
            "name": "node2", "url": "http://x", "success": False,
            "error": "<urlopen error [Errno 111] Connection refused>",
            "latency_ms": 0.3,
        }],
    })
    assert "&lt;urlopen error [Errno 111] Connection refused&gt;" in html


def test_app_checks_reports_reason_when_unconfigured():
    html = render_app_checks({
        "success": False, "reason": "no endpoints configured", "data": None
    })
    assert "no endpoints configured" in html


def test_app_checks_surfaces_the_endpoints_own_status_field():
    html = render_app_checks({
        "success": True, "count": 1, "healthy": 1,
        "data": [{
            "name": "slo", "url": "http://x", "success": True, "http_status": 200,
            "latency_ms": 2.0, "data": {"status": "unavailable"},
        }],
    })
    assert "unavailable" in html
    assert "1/1 healthy" in html


def test_containers_shows_which_runtime_answered():
    html = render_containers({
        "success": True, "runtime": "podman", "running_containers": ["brp-api"]
    })
    assert "podman" in html
    assert "1 running" in html


def test_report_renders_with_every_feature_degraded():
    #the minimized-install case: nothing optional is available
    data = {
        "system": {"hostname": "node2", "cpu_cores": 2},
        "core_metrics": {
            "cpu": 0.0,
            "memory": {"used_percent": 1.0, "available": 1, "swap_used_percent": 0.0},
            "disk": {"root_used_percent": 1.0, "root_free": 1},
            "network": {"bytes_sent": 0, "bytes_received": 0},
        },
        "uptime_seconds": 10,
        "health": {"status": "HEALTHY", "diagnosis": ["No issues detected"]},
        "features": {
            "services": {"success": False, "reason": "systemctl not available"},
            "failed_services": {"success": False, "reason": "unavailable"},
            "containers": {"success": False, "reason": "no container runtime"},
            "disk_details": {"success": False, "error": "permission denied"},
            "cpu_temperature": {"success": False, "reason": "no sensors available"},
            "app_checks": {"success": False, "reason": "no endpoints configured"},
        },
    }
    html = generate_html(data)
    assert "no sensors available" in html
    assert "no container runtime" in html
    assert "permission denied" in html
