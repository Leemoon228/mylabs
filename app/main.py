import socket
import time

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.models import (
    Error,
    HealthResponse,
    Node,
    NodeCreate,
    NodeStatus,
    NodeUpdate,
)

from app.metrics import (
    http_request_duration_seconds,
    http_requests_total,
    node_status_checks_total,
    nodes_created_total,
    nodes_deleted_total,
)

app = FastAPI(
    title="Server Monitoring API",
    description="API сервиса мониторинга серверов и сетевых узлов.",
    version="1.0.0",
)


nodes: dict[int, Node] = {}
next_node_id = 1


@app.get("/nodes", response_model=list[Node])
def list_nodes():
    return list(nodes.values())


@app.post(
    "/nodes",
    response_model=Node,
    status_code=status.HTTP_201_CREATED,
)
def create_node(node_data: NodeCreate):
    global next_node_id

    node = Node(
        id=next_node_id,
        **node_data.model_dump(),
    )

    nodes[node.id] = node
    nodes_created_total.inc()
    next_node_id += 1

    return node


@app.get("/nodes/{node_id}", response_model=Node)
def get_node(node_id: int):
    node = nodes.get(node_id)

    if node is None:
        raise HTTPException(
            status_code=404,
            detail=f"Node with id {node_id} not found",
        )

    return node


@app.put("/nodes/{node_id}", response_model=Node)
def update_node(node_id: int, node_data: NodeUpdate):
    node = nodes.get(node_id)

    if node is None:
        raise HTTPException(
            status_code=404,
            detail=f"Node with id {node_id} not found",
        )

    updated_data = node.model_dump()
    updated_data.update(node_data.model_dump(exclude_unset=True))

    updated_node = Node(**updated_data)
    nodes[node_id] = updated_node

    return updated_node


@app.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_node(node_id: int):
    if node_id not in nodes:
        raise HTTPException(
            status_code=404,
            detail=f"Node with id {node_id} not found",
        )

    del nodes[node_id]
    nodes_deleted_total.inc()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/nodes/{node_id}/status", response_model=NodeStatus)
def get_node_status(node_id: int):
    node = nodes.get(node_id)

    if node is None:
        raise HTTPException(
            status_code=404,
            detail=f"Node with id {node_id} not found",
        )

    started_at = time.perf_counter()
    node_status_checks_total.inc()

    try:
        with socket.create_connection(
            (node.host, node.port),
            timeout=2,
        ):
            node_status = "up"
    except OSError:
        node_status = "down"

    response_time_ms = (
        (time.perf_counter() - started_at) * 1000
        if node_status == "up"
        else None
    )

    return NodeStatus(
        node_id=node.id,
        status=node_status,
        response_time_ms=response_time_ms,
    )

@app.get("/metrics")
def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )

@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok")

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 404:
        return JSONResponse(
            status_code=404,
            content={
                "code": "NOT_FOUND",
                "message": str(exc.detail),
            },
        )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": "HTTP_ERROR",
            "message": str(exc.detail),
        },
    )

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    started_at = time.perf_counter()

    response = await call_next(request)

    duration = time.perf_counter() - started_at

    route = request.scope.get("route")
    path = route.path if route else request.url.path

    http_requests_total.labels(
        method=request.method,
        path=path,
        status=response.status_code,
    ).inc()

    http_request_duration_seconds.labels(
        method=request.method,
        path=path,
    ).observe(duration)

    return response