#format.py

def build_view(data, mode):
    base = {
        "timestamp": data["timestamp"],
        "system": data["system"],
        "core_metrics": data["core_metrics"],
    }

    if mode == "simple":
        return base

    # default mode
    base.update(
        {
            "uptime_seconds": data.get("uptime_seconds"),
            "health": {
                "status": data["health"]["status"],
                "diagnosis": data["health"]["diagnosis"],
            },
        }
    )

    if mode == "full":
        base.update(
            {
                "uptime_seconds": data.get("uptime_seconds"),
                "top_processes": data.get("top_processes"),
                "health": data["health"],
                "features": data.get("features"),
            }
        )

    return base