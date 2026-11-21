from .. import redis_conn

GAUGES = {
    "connected_clients": "pretix_redis_connected_clients",
    "blocked_clients": "pretix_redis_blocked_clients",
    "used_memory": "pretix_redis_used_memory_bytes",
    "maxmemory": "pretix_redis_maxmemory_bytes",
    "instantaneous_ops_per_sec": "pretix_redis_instantaneous_ops_per_second",
    "uptime_in_seconds": "pretix_redis_uptime_seconds",
}
COUNTERS = {
    "total_commands_processed": "pretix_redis_commands_processed_total",
    "total_connections_received": "pretix_redis_connections_received_total",
    "keyspace_hits": "pretix_redis_keyspace_hits_total",
    "keyspace_misses": "pretix_redis_keyspace_misses_total",
    "evicted_keys": "pretix_redis_evicted_keys_total",
    "expired_keys": "pretix_redis_expired_keys_total",
}


def collect():
    r = redis_conn.get_redis()
    if r is None:
        return []
    info = r.info()
    samples = []
    for key, name in list(GAUGES.items()) + list(COUNTERS.items()):
        if key in info:
            samples.append((name, {}, info[key]))
    for key, value in info.items():
        if key.startswith("db") and key[2:].isdigit() and isinstance(value, dict):
            samples.append(("pretix_redis_keys", {"db": key[2:]}, value.get("keys", 0)))
    return samples
