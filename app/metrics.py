from prometheus_client import Counter, Histogram


http_requests_total = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)

nodes_created_total = Counter(
    "nodes_created_total",
    "Total number of created nodes",
)

nodes_deleted_total = Counter(
    "nodes_deleted_total",
    "Total number of deleted nodes",
)

node_status_checks_total = Counter(
    "node_status_checks_total",
    "Total number of node status checks",
)