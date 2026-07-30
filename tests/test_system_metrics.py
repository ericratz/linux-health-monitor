"""
Parser-level tests for the /proc and /sys collectors.

These feed the parsers captured fixture text rather than the live host, so a
format regression is caught deterministically instead of only on the machine
that happens to produce the odd layout.
"""
from agent import system_metrics as sm


PROC_STAT = """cpu  207368 2846 227015 43179135 17684 0 109651 0 0 0
cpu0 25921 355 28376 5397391 2210 0 13706 0 0 0
intr 12345
ctxt 6789
"""

MEMINFO = """MemTotal:        6008440 kB
MemFree:         1593956 kB
MemAvailable:    4122200 kB
Buffers:          156036 kB
Cached:          2344184 kB
SwapCached:            0 kB
SwapTotal:       2097152 kB
SwapFree:        1048576 kB
HugePages_Total:       0
"""

NET_DEV = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 53883821   31824    0    0    0     0          0         0 53883821   31824    0    0    0     0       0          0
  eth0: 248588161  185159    0    0    0     0          0      4161  5929644   30190    0    0    0     0       0          0
"""


def test_cpu_line_parsed_from_fixture(monkeypatch):
    monkeypatch.setattr(sm, "_read_file", lambda path: PROC_STAT)
    busy, total = sm._read_proc_stat_cpu()
    values = [207368, 2846, 227015, 43179135, 17684, 0, 109651, 0, 0, 0]
    assert total == sum(values)
    #idle (43179135) and iowait (17684) are both non-busy
    assert busy == sum(values) - 43179135 - 17684


def test_cpu_percent_from_two_samples():
    #100 jiffies elapsed, 25 of them busy
    assert sm._cpu_percent((0, 0), (25, 100)) == 25.0


def test_cpu_percent_handles_missing_and_zero_delta():
    assert sm._cpu_percent(None, (1, 2)) == 0.0
    assert sm._cpu_percent((1, 2), None) == 0.0
    #counters that did not advance must not divide by zero
    assert sm._cpu_percent((5, 10), (5, 10)) == 0.0


def test_cpu_percent_is_clamped():
    #a counter rollback must not produce a negative or >100 percentage
    assert sm._cpu_percent((100, 100), (0, 200)) == 0.0
    assert sm._cpu_percent((0, 0), (500, 100)) == 100.0


def test_meminfo_converts_kb_to_bytes(monkeypatch):
    monkeypatch.setattr(sm, "_read_file", lambda path: MEMINFO)
    info = sm._read_meminfo()
    assert info["MemTotal"] == 6008440 * 1024
    #a unitless field is taken at face value
    assert info["HugePages_Total"] == 0


def test_memory_usage_derives_used_from_available(monkeypatch):
    monkeypatch.setattr(sm, "_read_file", lambda path: MEMINFO)
    mem = sm.get_memory_usage()
    assert mem["available"] == 4122200 * 1024
    expected = (6008440 - 4122200) / 6008440 * 100
    assert mem["used_percent"] == round(expected, 2)
    #half of swap is in use in the fixture
    assert mem["swap_used_percent"] == 50.0


def test_memory_usage_without_swap_does_not_divide_by_zero(monkeypatch):
    monkeypatch.setattr(sm, "_read_file", lambda path: "MemTotal: 100 kB\nMemAvailable: 50 kB\n")
    assert sm.get_memory_usage()["swap_used_percent"] == 0.0


def test_memory_usage_falls_back_when_memavailable_absent(monkeypatch):
    #kernels before 3.14 have no MemAvailable
    old = "MemTotal: 1000 kB\nMemFree: 100 kB\nBuffers: 50 kB\nCached: 150 kB\n"
    monkeypatch.setattr(sm, "_read_file", lambda path: old)
    assert sm.get_memory_usage()["available"] == 300 * 1024


def test_memory_usage_survives_unreadable_proc(monkeypatch):
    monkeypatch.setattr(sm, "_read_file", lambda path: None)
    mem = sm.get_memory_usage()
    assert mem == {"used_percent": 0.0, "available": 0, "swap_used_percent": 0.0}


def test_network_io_sums_every_interface(monkeypatch):
    monkeypatch.setattr(sm, "_read_file", lambda path: NET_DEV)
    net = sm.get_network_io()
    assert net["bytes_received"] == 53883821 + 248588161
    assert net["bytes_sent"] == 53883821 + 5929644


def test_network_io_survives_unreadable_proc(monkeypatch):
    monkeypatch.setattr(sm, "_read_file", lambda path: None)
    assert sm.get_network_io() == {"bytes_sent": 0, "bytes_received": 0}


def test_disk_io_rate_scales_sectors_to_bytes_per_second():
    #200 sectors over 0.5s = 400 sectors/s = 204800 B/s
    rate = sm._disk_io_rate((0, 0), (100, 200), 0.5)
    assert rate["read_bytes_per_sec"] == int(100 * 512 / 0.5)
    assert rate["write_bytes_per_sec"] == int(200 * 512 / 0.5)


def test_disk_io_rate_degrades_without_samples():
    assert sm._disk_io_rate(None, (1, 1), 1) is None
    assert sm._disk_io_rate((1, 1), None, 1) is None
    assert sm._disk_io_rate((1, 1), (2, 2), 0) is None


def test_physical_disk_filter_excludes_virtual_devices():
    for name in ("loop0", "ram3", "zram0", "dm-1", "sr0"):
        assert not sm._is_physical_disk(name), name


def test_physical_disk_filter_excludes_partitions(monkeypatch):
    #nvme0n1 is a disk; nvme0n1p1 is a partition, distinguished by the
    #kernel's 'partition' attribute rather than by a trailing digit
    monkeypatch.setattr(sm.os.path, "isdir", lambda p: True)
    monkeypatch.setattr(
        sm.os.path, "exists", lambda p: p.endswith("nvme0n1p1/partition")
    )
    assert sm._is_physical_disk("nvme0n1")
    assert not sm._is_physical_disk("nvme0n1p1")


def test_proc_pid_stat_handles_spaces_and_parens_in_comm(monkeypatch):
    #a process may name itself anything, including "(evil) name)"
    fields = " ".join(str(i) for i in range(3, 40))
    monkeypatch.setattr(sm, "_read_file", lambda path: f"42 ((evil) name)) S {fields}\n")
    comm, parsed = sm._proc_pid_stat(42)
    assert comm == "(evil) name)"
    assert parsed[0] == "S"


def test_proc_pid_stat_rejects_truncated_line(monkeypatch):
    monkeypatch.setattr(sm, "_read_file", lambda path: "42 (short) S 1 2 3\n")
    assert sm._proc_pid_stat(42) is None


def test_proc_pid_stat_returns_none_for_vanished_process(monkeypatch):
    monkeypatch.setattr(sm, "_read_file", lambda path: None)
    assert sm._proc_pid_stat(999999) is None


def test_proc_pid_rss_reads_statm_resident_field(monkeypatch):
    #size resident shared text lib data dt -- resident is the second field.
    #statm is used rather than stat's rss field, which the kernel documents
    #as inaccurate.
    monkeypatch.setattr(sm, "_read_file", lambda path: "5000 3922 1200 100 0 800 0\n")
    assert sm._proc_pid_rss(1) == 3922 * sm.PAGE_SIZE


def test_proc_pid_rss_degrades_for_vanished_or_odd_process(monkeypatch):
    monkeypatch.setattr(sm, "_read_file", lambda path: None)
    assert sm._proc_pid_rss(999999) == 0
    monkeypatch.setattr(sm, "_read_file", lambda path: "5000\n")
    assert sm._proc_pid_rss(1) == 0
    monkeypatch.setattr(sm, "_read_file", lambda path: "not numbers here\n")
    assert sm._proc_pid_rss(1) == 0


def test_opening_sample_skips_the_memory_read(monkeypatch):
    #memory is a level, not a delta, so only the closing sample needs it
    reads = []
    monkeypatch.setattr(sm, "_pid_list", lambda: [1])
    monkeypatch.setattr(sm, "_proc_pid_stat", lambda pid: ("x", ["S"] + [str(n) for n in range(20)]))

    def spy(pid):
        reads.append(pid)
        return 4096

    monkeypatch.setattr(sm, "_proc_pid_rss", spy)
    assert sm._sample_processes()[1][2] == 0
    assert reads == []
    assert sm._sample_processes(include_memory=True)[1][2] == 4096
    assert reads == [1]


def test_top_processes_uses_cpu_delta_not_total(monkeypatch):
    monkeypatch.setattr(sm, "_read_meminfo", lambda: {"MemTotal": 1000})
    #busy has a huge lifetime total but did nothing this interval;
    #spiky accumulated CLK_TCK jiffies (one full second of CPU)
    start = {1: ("busy", 10_000, 100), 2: ("spiky", 0, 100)}
    end = {1: ("busy", 10_000, 100), 2: ("spiky", sm.CLK_TCK, 100)}
    top = sm._top_processes(start, end, interval=1.0, limit=5)
    assert top[0]["name"] == "spiky"
    assert top[0]["cpu_percent"] == 100.0
    assert top[1]["cpu_percent"] == 0.0


def test_top_processes_handles_process_born_mid_interval(monkeypatch):
    monkeypatch.setattr(sm, "_read_meminfo", lambda: {"MemTotal": 1000})
    top = sm._top_processes({}, {7: ("new", 50, 250)}, interval=1.0, limit=5)
    #no baseline to subtract, so it reports no CPU rather than its whole life
    assert top[0]["cpu_percent"] == 0.0
    assert top[0]["memory_percent"] == 25.0


def test_top_processes_respects_limit(monkeypatch):
    monkeypatch.setattr(sm, "_read_meminfo", lambda: {"MemTotal": 1000})
    end = {pid: (f"p{pid}", pid * 10, 10) for pid in range(1, 20)}
    assert len(sm._top_processes({}, end, interval=1.0, limit=3)) == 3


def test_top_processes_without_memtotal_does_not_divide_by_zero(monkeypatch):
    monkeypatch.setattr(sm, "_read_meminfo", lambda: {})
    top = sm._top_processes({}, {1: ("x", 0, 500)}, interval=1.0, limit=1)
    assert top[0]["memory_percent"] == 0.0


def test_disk_usage_parses_df_portable_output(monkeypatch):
    output = (
        "Filesystem          1-blocks       Used     Available Capacity Mounted on\n"
        "/dev/sdf       1081101176832 4472086528 1021636734976       1% /\n"
    )
    monkeypatch.setattr(
        sm, "run_command", lambda cmd, timeout=3: {"stdout": output, "success": True}
    )
    disk = sm.get_disk_usage()
    assert disk["root_free"] == 1021636734976
    #percentage excludes root-reserved blocks, matching df's Capacity basis
    expected = 4472086528 / (4472086528 + 1021636734976) * 100
    assert disk["root_used_percent"] == round(expected, 2)


def test_disk_usage_degrades_when_df_missing(monkeypatch):
    monkeypatch.setattr(
        sm, "run_command", lambda cmd, timeout=3: {"stdout": "", "success": False}
    )
    assert sm.get_disk_usage() == {"root_used_percent": 0.0, "root_free": 0}


DF_ALL = (
    "Filesystem     1-blocks       Used  Available Capacity Mounted on\n"
    "/dev/sda1     100000000   50000000   50000000      50% /\n"
    "/dev/sda2     100000000   95000000    5000000      95% /var\n"
    "tmpfs           8000000          0    8000000       0% /run\n"
    "snapfuse         100000     100000          0     100% /snap/core24/1643\n"
    "/dev/sda3      10000000          0   10000000       0% /empty ro mount\n"
)

MOUNTS_ALL = (
    "/dev/sda1 / ext4 rw,relatime 0 0\n"
    "/dev/sda2 /var xfs rw,noatime 0 0\n"
    "tmpfs /run tmpfs rw,nosuid 0 0\n"
    "snapfuse /snap/core24/1643 fuse.snapfuse ro,nodev 0 0\n"
    "/dev/sda3 /empty\\040ro\\040mount ext4 ro,relatime 0 0\n"
)


def test_filesystems_reports_every_writable_mount(monkeypatch):
    monkeypatch.setattr(
        sm, "run_command", lambda cmd, timeout=3: {"stdout": DF_ALL, "success": True}
    )
    monkeypatch.setattr(sm, "_read_file", lambda path: MOUNTS_ALL)
    filesystems = sm.get_filesystems()
    mounts = [fs["mount"] for fs in filesystems]
    #worst first, so the mount about to cause an outage leads
    assert mounts[0] == "/var"
    assert filesystems[0]["used_percent"] == 95.0
    assert "/" in mounts
    #the snap image is read-only and sits at 100% by design
    assert "/snap/core24/1643" not in mounts
    #a read-only mount is excluded by option, whatever its type
    assert "/empty ro mount" not in mounts


def test_tmpfs_is_reported_because_it_can_fill(monkeypatch):
    #regression: /tmp and /dev/shm are tmpfs on a stock Ubuntu host, are sized
    #(1.7G each on a 4G node), and break services when full. Excluding them as
    #"just RAM" made a real outage invisible.
    df = (
        "Filesystem 1-blocks Used Available Capacity Mounted on\n"
        "tmpfs 1825361920 1825361920 0 100% /tmp\n"
        "tmpfs 1825361920 0 1825361920 0% /dev/shm\n"
        "tmpfs 5242880 4096 5238784 1% /run/lock\n"
    )
    mounts = (
        "tmpfs /tmp tmpfs rw,nosuid,nodev 0 0\n"
        "tmpfs /dev/shm tmpfs rw,nosuid,nodev 0 0\n"
        "tmpfs /run/lock tmpfs rw,nosuid,nodev,size=5120k 0 0\n"
    )
    monkeypatch.setattr(
        sm, "run_command", lambda cmd, timeout=3: {"stdout": df, "success": True}
    )
    monkeypatch.setattr(sm, "_read_file", lambda path: mounts)
    filesystems = sm.get_filesystems()
    by_mount = {fs["mount"]: fs for fs in filesystems}
    assert "/tmp" in by_mount
    assert "/dev/shm" in by_mount
    #a full /tmp must lead the list so it drives status and alerts
    assert filesystems[0]["mount"] == "/tmp"
    assert filesystems[0]["used_percent"] == 100.0


def test_dev_and_ramfs_stay_excluded(monkeypatch):
    #/dev holds device nodes and ramfs has no size limit, so neither can
    #meaningfully "fill"
    df = (
        "Filesystem 1-blocks Used Available Capacity Mounted on\n"
        "udev 2000000 0 2000000 0% /dev\n"
        "ramfs 1000 1000 0 100% /mnt/ramfs\n"
        "/dev/sda1 1000 500 500 50% /\n"
    )
    mounts = (
        "udev /dev devtmpfs rw 0 0\n"
        "ramfs /mnt/ramfs ramfs rw 0 0\n"
        "/dev/sda1 / ext4 rw 0 0\n"
    )
    monkeypatch.setattr(
        sm, "run_command", lambda cmd, timeout=3: {"stdout": df, "success": True}
    )
    monkeypatch.setattr(sm, "_read_file", lambda path: mounts)
    assert [fs["mount"] for fs in sm.get_filesystems()] == ["/"]


def test_filesystems_keeps_a_full_writable_mount(monkeypatch):
    #the read-only rule must never hide a genuinely full filesystem
    df = (
        "Filesystem 1-blocks Used Available Capacity Mounted on\n"
        "/dev/sdb1 1000 1000 0 100% /data\n"
    )
    monkeypatch.setattr(
        sm, "run_command", lambda cmd, timeout=3: {"stdout": df, "success": True}
    )
    monkeypatch.setattr(sm, "_read_file", lambda path: "/dev/sdb1 /data ext4 rw 0 0\n")
    filesystems = sm.get_filesystems()
    assert filesystems[0]["mount"] == "/data"
    assert filesystems[0]["used_percent"] == 100.0


def test_filesystems_handles_mountpoint_with_spaces(monkeypatch):
    df = (
        "Filesystem 1-blocks Used Available Capacity Mounted on\n"
        "/dev/sdc1 1000 500 500 50% /mnt/my disk\n"
    )
    monkeypatch.setattr(
        sm, "run_command", lambda cmd, timeout=3: {"stdout": df, "success": True}
    )
    #the kernel octal-escapes the space in /proc/mounts
    monkeypatch.setattr(
        sm, "_read_file", lambda path: "/dev/sdc1 /mnt/my\\040disk ext4 rw 0 0\n"
    )
    assert sm.get_filesystems()[0]["mount"] == "/mnt/my disk"


def test_filesystems_keeps_unknown_mounts_rather_than_hiding_them(monkeypatch):
    monkeypatch.setattr(
        sm, "run_command", lambda cmd, timeout=3: {"stdout": DF_ALL, "success": True}
    )
    #no /proc/mounts at all: better to over-report than to hide a real mount
    monkeypatch.setattr(sm, "_read_file", lambda path: None)
    mounts = [fs["mount"] for fs in sm.get_filesystems()]
    assert "/" in mounts and "/var" in mounts


def test_filesystems_degrades_when_df_missing(monkeypatch):
    monkeypatch.setattr(
        sm, "run_command", lambda cmd, timeout=3: {"stdout": "", "success": False}
    )
    monkeypatch.setattr(sm, "_read_file", lambda path: "")
    assert sm.get_filesystems() == []


def test_pressure_computes_iowait_share():
    #200 total jiffies elapsed, 50 of them iowait
    start = [100, 0, 100, 1000, 100, 0, 0, 0]
    end = [120, 0, 110, 1100, 150, 0, 0, 0]
    pressure = sm._pressure(start, end, {}, {}, 1.0)
    total_delta = sum(end) - sum(start)
    assert pressure["iowait_percent"] == round(50 / total_delta * 100, 1)


def test_pressure_swap_rates_from_vmstat():
    vm_start = {"pswpin": 0, "pswpout": 100, "pgmajfault": 10}
    vm_end = {"pswpin": 10, "pswpout": 150, "pgmajfault": 30}
    pressure = sm._pressure(None, None, vm_start, vm_end, 0.5)
    assert pressure["swap_in_bytes_per_sec"] == int(10 * sm.PAGE_SIZE / 0.5)
    assert pressure["swap_out_bytes_per_sec"] == int(50 * sm.PAGE_SIZE / 0.5)
    assert pressure["major_faults_per_sec"] == int(20 / 0.5)


def test_pressure_degrades_without_samples():
    pressure = sm._pressure(None, None, {}, {}, 1.0)
    assert pressure["iowait_percent"] is None
    assert pressure["swap_in_bytes_per_sec"] is None


def test_pressure_ignores_counter_rollback():
    #a counter that went backwards must not produce a negative rate
    pressure = sm._pressure(None, None, {"pswpout": 500}, {"pswpout": 100}, 1.0)
    assert pressure["swap_out_bytes_per_sec"] == 0


def test_runnable_count_from_loadavg(monkeypatch):
    monkeypatch.setattr(sm, "_read_file", lambda path: "0.1 0.2 0.3 4/586 12345\n")
    assert sm._runnable_count() == 4


def test_runnable_count_degrades(monkeypatch):
    monkeypatch.setattr(sm, "_read_file", lambda path: None)
    assert sm._runnable_count() is None
    monkeypatch.setattr(sm, "_read_file", lambda path: "0.1 0.2 0.3\n")
    assert sm._runnable_count() is None


def test_process_summary_counts_blocked_and_zombies(monkeypatch):
    states = {1: "S", 2: "Z", 3: "D", 4: "D", 5: "R"}
    monkeypatch.setattr(sm, "_pid_list", lambda: list(states))
    monkeypatch.setattr(
        sm, "_proc_pid_stat",
        lambda pid: ("proc", [states[pid]] + ["0"] * 25),
    )
    summary = sm.get_process_summary()
    assert summary == {"total": 5, "zombies": 1, "blocked": 2}


def test_uptime_parses_fractional_seconds(monkeypatch):
    monkeypatch.setattr(sm, "_read_file", lambda path: "54720.05 431791.44\n")
    assert sm.get_system_uptime() == 54720


def test_uptime_degrades_when_unreadable(monkeypatch):
    monkeypatch.setattr(sm, "_read_file", lambda path: None)
    assert sm.get_system_uptime() == 0


def test_load_average_parses_proc_loadavg(monkeypatch):
    monkeypatch.setattr(sm, "_read_file", lambda path: "0.75 0.45 0.23 2/604 97122\n")
    assert sm.get_load_average() == {"1min": 0.75, "5min": 0.45, "15min": 0.23}


def test_load_average_falls_back_to_stdlib(monkeypatch):
    monkeypatch.setattr(sm, "_read_file", lambda path: None)
    monkeypatch.setattr(sm.os, "getloadavg", lambda: (1.0, 2.0, 3.0))
    assert sm.get_load_average() == {"1min": 1.0, "5min": 2.0, "15min": 3.0}


def test_cpu_temperature_prefers_cpu_sensor_over_ambient(monkeypatch):
    monkeypatch.setattr(
        sm, "_thermal_zone_readings",
        lambda: [("acpitz", 40.0), ("x86_pkg_temp", 55.0)],
    )
    temp = sm.get_cpu_temperature()
    assert temp["success"] and temp["source"] == "x86_pkg_temp"
    assert temp["celsius"] == 55.0


def test_cpu_temperature_averages_multi_core_readings(monkeypatch):
    monkeypatch.setattr(sm, "_thermal_zone_readings", lambda: [])
    monkeypatch.setattr(
        sm, "_hwmon_readings",
        lambda: [("coretemp", 50.0), ("coretemp", 60.0), ("acpitz", 30.0)],
    )
    temp = sm.get_cpu_temperature()
    assert temp["source"] == "coretemp"
    assert temp["celsius"] == 55.0


def test_cpu_temperature_reports_absence_gracefully(monkeypatch):
    #the common case on VMs, WSL2 and minimized installs with no sensors
    monkeypatch.setattr(sm, "_thermal_zone_readings", lambda: [])
    monkeypatch.setattr(sm, "_hwmon_readings", lambda: [])
    temp = sm.get_cpu_temperature()
    assert temp["success"] is False
    assert "reason" in temp


def test_read_file_returns_none_instead_of_raising():
    assert sm._read_file("/proc/definitely-not-a-real-file") is None


def test_live_collectors_return_expected_shapes():
    #exercises the real host once, guarding the contract the report depends on
    cpu, top, disk_io, pressure = sm.get_cpu_snapshot(interval=0.05)
    assert set(pressure) == {
        "iowait_percent", "runnable", "swap_in_bytes_per_sec",
        "swap_out_bytes_per_sec", "major_faults_per_sec",
    }
    for filesystem in sm.get_filesystems():
        assert set(filesystem) == {"mount", "device", "used_percent", "free"}
    assert set(sm.get_process_summary()) == {"total", "zombies", "blocked"}
    assert isinstance(cpu, float) and 0.0 <= cpu <= 100.0
    assert isinstance(top, list)
    for proc in top:
        assert set(proc) == {"pid", "name", "cpu_percent", "memory_percent"}
    if disk_io is not None:
        assert set(disk_io) == {"read_bytes_per_sec", "write_bytes_per_sec"}
    assert set(sm.get_memory_usage()) == {
        "used_percent", "available", "swap_used_percent"
    }
    assert set(sm.get_disk_usage()) == {"root_used_percent", "root_free"}
    assert set(sm.get_network_io()) == {"bytes_sent", "bytes_received"}
    assert set(sm.get_load_average()) == {"1min", "5min", "15min"}
