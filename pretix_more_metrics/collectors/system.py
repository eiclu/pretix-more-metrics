"""
Host metrics read from /proc (Linux only).

Inside a container, /proc/stat, /proc/meminfo and /proc/loadavg show the values of the
whole host, not of the container. That is what we want on a single server.
"""
import os

PROC = "/proc"

CPU_MODES = ("user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal")
MEMINFO = {
    "MemTotal": "pretix_host_memory_total_bytes",
    "MemAvailable": "pretix_host_memory_available_bytes",
    "MemFree": "pretix_host_memory_free_bytes",
    "Buffers": "pretix_host_memory_buffers_bytes",
    "Cached": "pretix_host_memory_cached_bytes",
    "SwapTotal": "pretix_host_swap_total_bytes",
    "SwapFree": "pretix_host_swap_free_bytes",
}


def _read(name):
    with open(os.path.join(PROC, name)) as f:
        return f.read()


def collect():
    if not os.path.exists(os.path.join(PROC, "stat")):
        return []

    samples = []
    ticks = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    cpus = 0
    for line in _read("stat").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "cpu":
            for mode, value in zip(CPU_MODES, parts[1:]):
                samples.append(("pretix_host_cpu_seconds_total", {"mode": mode}, int(value) / ticks))
        elif parts[0].startswith("cpu") and parts[0][3:].isdigit():
            cpus += 1
    samples.append(("pretix_host_cpus", {}, cpus or os.cpu_count()))

    load = _read("loadavg").split()
    samples += [
        ("pretix_host_load1", {}, float(load[0])),
        ("pretix_host_load5", {}, float(load[1])),
        ("pretix_host_load15", {}, float(load[2])),
    ]

    for line in _read("meminfo").splitlines():
        key, _, rest = line.partition(":")
        if key in MEMINFO:
            value = rest.split()
            factor = 1024 if len(value) > 1 and value[1] == "kB" else 1
            samples.append((MEMINFO[key], {}, int(value[0]) * factor))
    return samples
