"""Pydantic request/response schemas."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EnqueueRequest(BaseModel):
    task: str = Field(..., description="Registered task name, e.g. 'flaky'")
    payload: Dict[str, Any] = Field(default_factory=dict)
    queue: str = "default"
    priority: int = 0
    max_attempts: int = Field(default=3, ge=1, le=25)
    delay_seconds: float = Field(default=0, ge=0)
    idempotency_key: Optional[str] = None


class QueueLimitRequest(BaseModel):
    concurrency: int = Field(..., ge=0, le=1000)


class SeedRequest(BaseModel):
    count: int = Field(default=25, ge=1, le=500)
