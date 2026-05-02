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


def format_core(core):
    core = dict(core)

    core["memory"] = format_memory(core.get("memory", {}))
    core["disk"] = format_disk(core.get("disk", {}))
    core["network"] = format_network(core.get("network", {}))

    return core


def generate_html(data):
    system = data.get("system", {})
    core = format_core(data.get("core_metrics", {}))
    uptime = data.get("uptime_seconds")
    if uptime is not None:
        uptime = format_uptime(uptime)
    top_processes = data.get("top_processes")
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
        pre {{
            background: #111;
            padding: 10px;
            border-radius: 6px;
            overflow-x: auto;
        }}
    </style>
</head>

<body>

<h1>Linux Health Monitor</h1>
<p>Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
"""

    html += render_card("System", json.dumps(system, indent=2))
    html += render_card("Core Metrics", json.dumps(core, indent=2))

    if uptime is not None:
        html += render_card("Uptime", uptime)

    if status:
        css_class = {
            "HEALTHY": "good",
            "WARNING": "warn",
            "CRITICAL": "bad"
        }.get(status, "warn")

        html += f"""
<div class="card">
    <h2>Health</h2>
    <p class="{css_class}">{status}</p>
    <pre>{json.dumps(diagnosis, indent=2)}</pre>
</div>
"""

    if top_processes:
        html += render_card("Top Processes", json.dumps(top_processes, indent=2))

    if features:
        html += render_card("Features", json.dumps(features, indent=2))

    html += """
</body>
</html>
"""

    return html