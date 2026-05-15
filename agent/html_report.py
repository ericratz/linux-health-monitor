from datetime import datetime, timezone
import json


def format_uptime(seconds):
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def format_bytes(num):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024:
            return f"{num:.2f} {unit}"
        num /= 1024
    return f"{num:.2f} PB"


def format_network(network):
    network = dict(network)
    if isinstance(network.get("bytes_sent"), (int, float)):
        network["bytes_sent"] = format_bytes(network["bytes_sent"])
    if isinstance(network.get("bytes_received"), (int, float)):
        network["bytes_received"] = format_bytes(network["bytes_received"])
    return network


def format_memory(memory):
    memory = dict(memory)
    if isinstance(memory.get("available"), (int, float)):
        memory["available"] = format_bytes(memory["available"])
    return memory


def format_disk(disk):
    disk = dict(disk)
    if isinstance(disk.get("root_free"), (int, float)):
        disk["root_free"] = format_bytes(disk["root_free"])
    return disk


def format_disk_details(features):
    features = dict(features)
    disk_details = dict(features.get("disk_details", {}))
    data = disk_details.get("data", [])
    for item in data:
        if isinstance(item.get("size_bytes"), (int, float)):
            item["size_bytes"] = format_bytes(item["size_bytes"])
    disk_details["data"] = data
    features["disk_details"] = disk_details
    return features


def render_card(title, content):
    return f"""
<div class="card">
    <h2>{title}</h2>
    <pre>{content}</pre>
</div>
"""


def render_services(services):
    if not services.get("success"):
        return f'<p class="muted">{services.get("reason", "unavailable")}</p>'
    rows = "".join(
        f'<li>{s["service"]}: <span class="mono">{s.get("status", "unknown")}</span></li>'
        for s in services.get("data") or []
    )
    return f"<ul>{rows}</ul>" if rows else '<p class="muted">No services checked</p>'


def render_docker(docker):
    if not docker.get("success"):
        return f'<p class="muted">{docker.get("reason", "unavailable")}</p>'
    containers = docker.get("running_containers", [])
    if not containers:
        return '<p class="muted">No containers running</p>'
    rows = "".join(f"<li>{c}</li>" for c in containers)
    return f"<p>{len(containers)} running</p><ul>{rows}</ul>"


def render_disk_details(disk_details):
    if not disk_details.get("success"):
        return f'<p class="muted">{disk_details.get("error", "unavailable")}</p>'
    data = disk_details.get("data") or []
    if not data:
        return '<p class="muted">No data</p>'
    rows = "".join(
        f"<tr><td>{item['name']}</td><td>{item['size_bytes']}</td></tr>"
        for item in data
    )
    return f'<table><tbody>{rows}</tbody></table>'


def render_failed_services(failed):
    if not failed.get("success"):
        return f'<p class="muted">{failed.get("reason", "unavailable")}</p>'
    if failed["count"] == 0:
        return '<p class="muted">None</p>'
    rows = "".join(f'<li class="bad">{s}</li>' for s in failed["services"])
    return f"<ul>{rows}</ul>"


def render_cpu_temp(temp):
    if not temp.get("success"):
        return f'<p class="muted">{temp.get("reason", "unavailable")}</p>'
    return f'<p>{temp["celsius"]}°C <span class="muted">({temp["source"]})</span></p>'


def render_features_card(features):
    services_html = render_services(features.get("services") or {})
    failed_html = render_failed_services(features.get("failed_services") or {})
    docker_html = render_docker(features.get("docker") or {})
    disk_html = render_disk_details((features.get("disk_details") or {}).copy())
    temp_html = render_cpu_temp(features.get("cpu_temperature") or {})
    return f"""
<div class="card">
    <h2>Features</h2>
    <h3>Services</h3>
    {services_html}
    <h3>Failed Services</h3>
    {failed_html}
    <h3>Docker</h3>
    {docker_html}
    <h3>Disk Usage <span class="muted">(/var/log)</span></h3>
    {disk_html}
    <h3>CPU Temperature</h3>
    {temp_html}
</div>
"""


def format_percents(core):
    core = dict(core)
    if isinstance(core.get("cpu"), (int, float)):
        core["cpu"] = f"{core['cpu']}%"
    memory = dict(core.get("memory", {}))
    for key in ("used_percent", "swap_used_percent"):
        if isinstance(memory.get(key), (int, float)):
            memory[key] = f"{memory[key]}%"
    core["memory"] = memory
    disk = dict(core.get("disk", {}))
    if isinstance(disk.get("root_used_percent"), (int, float)):
        disk["root_used_percent"] = f"{disk['root_used_percent']}%"
    core["disk"] = disk
    return core


def format_process_percents(procs):
    result = []
    for p in procs:
        p = dict(p)
        if isinstance(p.get("cpu_percent"), (int, float)):
            p["cpu_percent"] = f"{p['cpu_percent']}%"
        if isinstance(p.get("memory_percent"), (int, float)):
            p["memory_percent"] = f"{p['memory_percent']}%"
        result.append(p)
    return result


def format_core(core):
    core = dict(core)
    core["memory"] = format_memory(core.get("memory", {}))
    core["disk"] = format_disk(core.get("disk", {}))
    core["network"] = format_network(core.get("network", {}))
    return core


def humanize_view(view):
    """Format bytes, percentages, time, and normalized load for human-readable JSON output (-H)."""
    view = dict(view)
    cores = view.get("system", {}).get("cpu_cores") or 1
    if "core_metrics" in view:
        core = format_percents(dict(view["core_metrics"]))
        core["memory"] = format_memory(core.get("memory", {}))
        core["disk"] = format_disk(core.get("disk", {}))
        core["network"] = format_network(core.get("network", {}))
        load = dict(core.get("load", {}))
        for key in ("1min", "5min", "15min"):
            if isinstance(load.get(key), (int, float)):
                load[key] = f"{round(load[key] / cores * 100, 1)}%"
        core["load"] = load
        if core.get("disk_io"):
            dio = dict(core["disk_io"])
            for key in ("read_bytes_per_sec", "write_bytes_per_sec"):
                if isinstance(dio.get(key), (int, float)):
                    dio[key] = f"{format_bytes(dio[key])}/s"
            core["disk_io"] = dio
        view["core_metrics"] = core
    if "uptime_seconds" in view:
        view["uptime"] = format_uptime(view.pop("uptime_seconds"))
    if view.get("top_processes"):
        view["top_processes"] = format_process_percents(view["top_processes"])
    if view.get("features"):
        view["features"] = format_disk_details(view["features"])
    return view


def generate_html(data):
    system = data.get("system", {})
    core = format_percents(format_core(data.get("core_metrics", {})))
    uptime = data.get("uptime_seconds")
    if uptime is not None:
        uptime = format_uptime(uptime)
    _raw_procs = data.get("top_processes")
    top_processes = format_process_percents(_raw_procs) if _raw_procs else None
    features = format_disk_details(data.get("features", {}))
    status = data.get("health", {}).get("status")
    diagnosis = data.get("health", {}).get("diagnosis", [])

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Linux Health Monitor Report</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 40px;
            background: #0f1115;
            color: #e6e6e6;
        }}
        .card {{
            background: #1a1d24;
            padding: 15px;
            margin-bottom: 10px;
            border-radius: 8px;
        }}
        .good {{ color: #4caf50; }}
        .warn {{ color: #ff9800; }}
        .bad {{ color: #f44336; }}
        .muted {{ color: #888; font-size: 0.9em; }}
        .mono {{ font-family: monospace; }}
        pre {{
            background: #111;
            padding: 10px;
            border-radius: 6px;
            overflow-x: auto;
        }}
        h3 {{
            margin: 14px 0 6px;
            font-size: 0.95em;
            color: #aaa;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        ul {{ margin: 4px 0 0 18px; padding: 0; }}
        li {{ margin: 2px 0; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 4px; }}
        td {{ padding: 4px 12px 4px 0; font-size: 0.95em; }}
        td:last-child {{ color: #aaa; text-align: right; }}
    </style>
</head>

<body>

<h1>Linux Health Monitor</h1>
<p>Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
"""

    html += render_card("System", json.dumps(system, indent=2))
    html += render_card("Core Metrics", json.dumps(core, indent=2))

    if uptime is not None:
        html += f"""
<div class="card">
    <h2>Uptime</h2>
    <p>{uptime}</p>
</div>
"""

    if status:
        css_class = {
            "HEALTHY": "good",
            "WARNING": "warn",
            "CRITICAL": "bad"
        }.get(status, "warn")
        diag_items = "".join(f"<li>{d}</li>" for d in diagnosis)

        html += f"""
<div class="card">
    <h2>Health</h2>
    <p class="{css_class}" style="font-size:1.2em; font-weight:bold; margin:0 0 8px">{status}</p>
    <ul>{diag_items}</ul>
</div>
"""

    if top_processes:
        html += render_card("Top Processes", json.dumps(top_processes, indent=2))

    if features:
        html += render_features_card(features)

    html += """
</body>
</html>
"""

    return html