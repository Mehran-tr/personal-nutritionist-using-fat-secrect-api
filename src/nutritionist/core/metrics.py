"""Prometheus metrics, shared by every layer that does I/O.

Label values are always low-cardinality (route *templates*, fixed names). Raw
paths, user ids or food ids must never become labels.

Scaling model: one uvicorn worker per container, scaled with replicas. Each
replica exposes its own /metrics and Prometheus aggregates them. That avoids
prometheus_client's multiprocess mode.
"""

from prometheus_client import Counter, Histogram

_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests handled.", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Time to produce the full response.",
    ["method", "route"],
    buckets=_LATENCY_BUCKETS,
)
DB_QUERY_LATENCY = Histogram(
    "db_query_duration_seconds", "SQL statement execution time.", buckets=_LATENCY_BUCKETS
)
DB_SLOW_QUERIES = Counter("db_slow_queries_total", "Statements over the slow-query threshold.")
UPSTREAM_LATENCY = Histogram(
    "upstream_request_duration_seconds",
    "Calls to external APIs, per attempt.",
    ["service", "outcome"],
    buckets=_LATENCY_BUCKETS,
)
CACHE_REQUESTS = Counter("cache_requests_total", "Cache lookups.", ["cache", "result"])
BACKGROUND_TASKS = Counter("background_tasks_total", "Background tasks.", ["name", "outcome"])
