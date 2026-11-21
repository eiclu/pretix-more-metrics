from django.db import connection

# Every state PostgreSQL reports in pg_stat_activity, so the series exist even when they are 0.
STATES = (
    "active", "idle", "idle in transaction", "idle in transaction (aborted)",
    "fastpath function call", "disabled",
)


def collect():
    if connection.vendor != "postgresql":
        return []

    samples = []
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COALESCE(state, 'unknown'), count(*) FROM pg_stat_activity "
            "WHERE datname = current_database() GROUP BY 1"
        )
        counts = dict(cursor.fetchall())
        for state in STATES:
            samples.append(("pretix_db_connections", {"state": state}, counts.pop(state, 0)))
        for state, c in counts.items():
            samples.append(("pretix_db_connections", {"state": state}, c))

        cursor.execute("SELECT setting::int FROM pg_settings WHERE name = 'max_connections'")
        samples.append(("pretix_db_max_connections", {}, cursor.fetchone()[0]))

        cursor.execute(
            "SELECT xact_commit, xact_rollback, deadlocks, blks_read, blks_hit, "
            "pg_database_size(current_database()) "
            "FROM pg_stat_database WHERE datname = current_database()"
        )
        row = cursor.fetchone()
        if row:
            commit, rollback, deadlocks, blks_read, blks_hit, size = row
            samples += [
                ("pretix_db_transactions_total", {"result": "commit"}, commit),
                ("pretix_db_transactions_total", {"result": "rollback"}, rollback),
                ("pretix_db_deadlocks_total", {}, deadlocks),
                ("pretix_db_blocks_total", {"source": "disk"}, blks_read),
                ("pretix_db_blocks_total", {"source": "cache"}, blks_hit),
                ("pretix_db_size_bytes", {}, size),
            ]
    return samples
