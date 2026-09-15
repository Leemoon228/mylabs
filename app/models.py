from pydantic import BaseModel, Field
from typing import Literal


class NodeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    description: str | None = Field(default=None, max_length=500)


class NodeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    description: str | None = Field(default=None, max_length=500)


class Node(BaseModel):
    id: int
    name: str
    host: str
    port: int
    description: str | None = None


class NodeStatus(BaseModel):
    node_id: int
    status: Literal["up", "down"]
    response_time_ms: float | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"]


class Error(BaseModel):
    code: str
    message: str