import socket
import time

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.models import (
    Error,
    HealthResponse,
    Node,
    NodeCreate,
    NodeStatus,
    NodeUpdate,
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