import socket
import time

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app.logging_config import setup_logging
from app.tracing import setup_tracing
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


logger = setup_logging()
tracer = setup_tracing()


app = FastAPI(
    title="Server Monitoring API",
    description="API сервиса мониторинга серверов и сетевых узлов.",
    version="1.0.0",
)


FastAPIInstrumentor.instrument_app(app)


nodes: dict[int, Node] = {}
next_node_id = 1


@app.get("/nodes", response_model=list[Node])
def list_nodes():
    logger.info(
        "nodes.listed",
        extra={
            "count": len(nodes),
        },
    )

    return list(nodes.values())


@app.post(
    "/nodes",
    response_model=Node,
    status_code=status.HTTP_201_CREATED,
)
def create_node(node_data: NodeCreate):
    global next_node_id

    with tracer.start_as_current_span("node.create") as span:
        span.set_attribute("node.name", node_data.name)
        span.set_attribute("node.host", node_data.host)
        span.set_attribute("node.port", node_data.port)

        node = Node(
            id=next_node_id,
            **node_data.model_dump(),
        )

        nodes[node.id] = node
        nodes_created_total.inc()
        next_node_id += 1

    logger.info(
        "node.created",
        extra={
            "node_id": node.id,
            "node_name": node.name,
            "host": node.host,
            "port": node.port,
        },
    )

    return node


@app.get("/nodes/{node_id}", response_model=Node)
def get_node(node_id: int):
    node = nodes.get(node_id)

    if node is None:
        logger.warning(
            "node.not_found",
            extra={
                "node_id": node_id,
            },
        )

        raise HTTPException(
            status_code=404,
            detail=f"Node with id {node_id} not found",
        )

    logger.info(
        "node.retrieved",
        extra={
            "node_id": node_id,
        },
    )

    return node


@app.put("/nodes/{node_id}", response_model=Node)
def update_node(node_id: int, node_data: NodeUpdate):
    node = nodes.get(node_id)

    if node is None:
        logger.warning(
            "node.not_found",
            extra={
                "node_id": node_id,
            },
        )

        raise HTTPException(
            status_code=404,
            detail=f"Node with id {node_id} not found",
        )

    updated_data = node.model_dump()
    updated_data.update(
        node_data.model_dump(exclude_unset=True)
    )

    updated_node = Node(**updated_data)
    nodes[node_id] = updated_node

    logger.info(
        "node.updated",
        extra={
            "node_id": node_id,
            "node_name": updated_node.name,
            "host": updated_node.host,
            "port": updated_node.port,
        },
    )

    return updated_node


@app.delete(
    "/nodes/{node_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_node(node_id: int):
    if node_id not in nodes:
        logger.warning(
            "node.not_found",
            extra={
                "node_id": node_id,
            },
        )

        raise HTTPException(
            status_code=404,
            detail=f"Node with id {node_id} not found",
        )

    del nodes[node_id]
    nodes_deleted_total.inc()

    logger.info(
        "node.deleted",
        extra={
            "node_id": node_id,
        },
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get(
    "/nodes/{node_id}/status",
    response_model=NodeStatus,
)
def get_node_status(node_id: int):
    node = nodes.get(node_id)

    if node is None:
        logger.warning(
            "node.not_found",
            extra={
                "node_id": node_id,
            },
        )

        raise HTTPException(
            status_code=404,
            detail=f"Node with id {node_id} not found",
        )

    with tracer.start_as_current_span("node.status_check") as span:
        span.set_attribute("node.id", node.id)
        span.set_attribute("node.host", node.host)
        span.set_attribute("node.port", node.port)

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

        span.set_attribute("node.status", node_status)

    response_time_ms = (
        (time.perf_counter() - started_at) * 1000
        if node_status == "up"
        else None
    )

    logger.info(
        "node.status_checked",
        extra={
            "node_id": node_id,
            "status": node_status,
            "response_time_ms": (
                round(response_time_ms, 2)
                if response_time_ms is not None
                else None
            ),
        },
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
    logger.info("health.checked")

    return HealthResponse(status="ok")


@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request,
    exc: HTTPException,
):
    logger.warning(
        "http.error",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": exc.status_code,
        },
    )

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

    if request.url.path == "/metrics":
        return await call_next(request)

    try:
        response = await call_next(request)
    except Exception:
        duration = (time.perf_counter() - started_at) * 1000

        logger.exception(
            "http.request_failed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "duration_ms": round(duration, 2),
            },
        )

        raise

    duration = (time.perf_counter() - started_at) * 1000

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
    ).observe(duration / 1000)

    logger.info(
        "http.request",
        extra={
            "method": request.method,
            "path": path,
            "status_code": response.status_code,
            "duration_ms": round(duration, 2),
        },
    )

    return response