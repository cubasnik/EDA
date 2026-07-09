"""Pydantic request/response schemas for the EDA REST API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------- #
# Service templates
# --------------------------------------------------------------------- #
class TemplateCreateRequest(BaseModel):
    name: str = Field(..., examples=["vlan-activation"])
    version: str = Field(default="1.0")
    description: str = Field(default="")
    steps: List[str] = Field(
        default_factory=list,
        description="Ordered list of activation step names executed by the engine",
    )
    parameters_schema: Dict[str, Any] = Field(default_factory=dict)


class TemplateResponse(BaseModel):
    id: str
    name: str
    version: str
    description: str
    steps: List[str]
    parameters_schema: Dict[str, Any]
    created_at: float


# --------------------------------------------------------------------- #
# Network elements
# --------------------------------------------------------------------- #
class NetworkElementCreateRequest(BaseModel):
    name: str
    ne_type: str = Field(default="generic")
    management_ip: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NetworkElementResponse(BaseModel):
    id: str
    name: str
    ne_type: str
    management_ip: str
    status: str
    blocked: bool
    metadata: Dict[str, Any]
    created_at: float


# --------------------------------------------------------------------- #
# Activations
# --------------------------------------------------------------------- #
class ActivationCreateRequest(BaseModel):
    template_id: str
    ne_id: Optional[str] = None
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Free-form activation parameters. Special keys understood by the engine: "
            "'fail_at_step' (str) injects a deterministic failure at that step; "
            "'auto_retry' ({'max_attempts': int, 'backoff_seconds': float}) makes the "
            "engine retry the workflow automatically before giving up; 'webhook_url' "
            "(str) is POSTed the final activation state once it reaches ACTIVE/FAILED/"
            "DEACTIVATED."
        ),
    )


class ActivationResponse(BaseModel):
    id: str
    template_id: str
    ne_id: Optional[str]
    params: Dict[str, Any]
    state: str
    current_step: Optional[str]
    error: Optional[str]
    attempts: int
    created_at: float
    updated_at: float


class BatchActivationCreateRequest(BaseModel):
    activations: List[ActivationCreateRequest]


class BatchActivationItemResult(BaseModel):
    ok: bool
    activation: Optional[ActivationResponse] = None
    error: Optional[str] = None


class LogEntry(BaseModel):
    ts: float
    message: str


class ActivationLogsResponse(BaseModel):
    activation_id: str
    logs: List[LogEntry]


# --------------------------------------------------------------------- #
# Alarms
# --------------------------------------------------------------------- #
class AlarmResponse(BaseModel):
    id: str
    severity: str
    source: str
    text: str
    raised_at: float
    cleared_at: Optional[float]


# --------------------------------------------------------------------- #
# Health / version
# --------------------------------------------------------------------- #
class HealthResponse(BaseModel):
    status: str
    ne_name: str
    ne_type: str
    version: str
    uptime_seconds: float


class ErrorResponse(BaseModel):
    detail: str
