import pytest

from pretix_more_metrics.collectors import database, redis_info, system

STAT = """cpu  100 0 50 1000 10 0 5 0 0 0
cpu0 50 0 25 500 5 0 2 0 0 0
cpu1 50 0 25 500 5 0 3 0 0 0
intr 12345
"""
MEMINFO = """MemTotal:        2048 kB
MemFree:          512 kB
MemAvailable:    1024 kB
Buffers:           10 kB
Cached:           100 kB
SwapTotal:          0 kB
SwapFree:           0 kB
"""


@pytest.fixture
def proc(tmp_path, monkeypatch):
    (tmp_path / "stat").write_text(STAT)
    (tmp_path / "meminfo").write_text(MEMINFO)
    (tmp_path / "loadavg").write_text("0.50 0.25 0.10 1/100 1234\n")
    monkeypatch.setattr(system, "PROC", str(tmp_path))
    monkeypatch.setattr(system.os, "sysconf", lambda name: 100)
    return tmp_path


def test_system(proc):
    s = {(n, tuple(lbl.items())): v for n, lbl, v in system.collect()}
    assert s[("pretix_host_cpu_seconds_total", (("mode", "user"),))] == 1.0
    assert s[("pretix_host_cpu_seconds_total", (("mode", "idle"),))] == 10.0
    assert s[("pretix_host_cpus", ())] == 2
    assert s[("pretix_host_load1", ())] == 0.5
    assert s[("pretix_host_memory_total_bytes", ())] == 2048 * 1024
    assert s[("pretix_host_memory_available_bytes", ())] == 1024 * 1024


def test_system_without_proc(tmp_path, monkeypatch):
    monkeypatch.setattr(system, "PROC", str(tmp_path / "nope"))
    assert system.collect() == []


def test_redis_info(monkeypatch):
    class FakeRedis:
        def info(self):
            return {"connected_clients": 7, "total_commands_processed": 1234, "used_memory": 1000,
                    "db0": {"keys": 42, "expires": 3}, "redis_version": "7.2"}

    monkeypatch.setattr(redis_info.redis_conn, "get_redis", lambda: FakeRedis())
    s = {(n, tuple(lbl.items())): v for n, lbl, v in redis_info.collect()}
    assert s[("pretix_redis_connected_clients", ())] == 7
    assert s[("pretix_redis_commands_processed_total", ())] == 1234
    assert s[("pretix_redis_keys", (("db", "0"),))] == 42


@pytest.mark.django_db
def test_database_skipped_on_sqlite():
    assert database.collect() == []
