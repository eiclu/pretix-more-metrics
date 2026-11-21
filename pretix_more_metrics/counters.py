"""
Event-driven counters. They use pretix's own metric classes, so they are stored in the
same Redis hash (``pretix_metrics``) and served by pretix's /metrics like the built-in ones.
Label values must not contain quotes or backslashes, pretix does not escape them.
"""
from pretix.base.metrics import Counter

orders_placed_total = Counter(
    "pretix_orders_placed_total", "Orders placed",
    ["organizer", "event", "sales_channel"],
)
order_positions_placed_total = Counter(
    "pretix_order_positions_placed_total", "Order positions (tickets, add-ons) in placed orders",
    ["organizer", "event", "sales_channel"],
)
orders_paid_total = Counter(
    "pretix_orders_paid_total", "Orders marked as paid",
    ["organizer", "event"],
)
shop_task_errors_total = Counter(
    "pretix_shop_task_errors_total", "Failed cart and checkout tasks by reason",
    ["task", "reason"],
)
