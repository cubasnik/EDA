"""
Domain model for EDA: service templates, service activations (instances),
managed network elements and fault-management alarms. Kept dependency-free
(plain dataclasses) so it can be reused by both the API layer and the
CLI/tests without pulling in FastAPI/Pydantic.
"""
from __future__ import annotations

import enum
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def now() -> float:
    return time.time()


class ActivationState(str, enum.Enum):
    CREATED = "CREATED"
    HELD = "HELD"
    VALIDATING = "VALIDATING"
    ACTIVATING = "ACTIVATING"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    DEACTIVATING = "DEACTIVATING"
    DEACTIVATED = "DEACTIVATED"

    @classmethod
    def terminal_states(cls) -> List["ActivationState"]:
        return [cls.ACTIVE, cls.FAILED, cls.DEACTIVATED]


class NetworkElementStatus(str, enum.Enum):
    REACHABLE = "REACHABLE"
    UNREACHABLE = "UNREACHABLE"
    UNKNOWN = "UNKNOWN"


class AlarmSeverity(str, enum.Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    WARNING = "WARNING"


@dataclass
class ServiceTemplate:
    """
    A service template describes a re-usable activation workflow, e.g.
    "vlan-activation" or "subscriber-session-activation". It is the EDA
    equivalent of an EDA "Service Model" deployed through the
    Activation Orchestrator Deployer.
    """
    id: str
    name: str
    version: str
    description: str
    steps: List[str] = field(default_factory=list)
    parameters_schema: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "steps": self.steps,
            "parameters_schema": self.parameters_schema,
            "created_at": self.created_at,
        }

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "ServiceTemplate":
        return ServiceTemplate(
            id=row["id"],
            name=row["name"],
            version=row["version"],
            description=row["description"],
            steps=json.loads(row["steps"]),
            parameters_schema=json.loads(row["parameters_schema"]),
            created_at=row["created_at"],
        )


@dataclass
class Activation:
    """
    A service activation is a running (or completed) instance of a
    ServiceTemplate, applied against a target network element with a
    concrete set of parameters. This is the EDA equivalent of a
    "service instance" processed by the Activation Engine/Orchestrator.

    ``attempts`` counts how many times the workflow has been (re-)run,
    incremented both by automatic retries (``params.auto_retry``) and by
    manual ``POST /activations/{id}/retry`` calls - the EDA equivalent of
    the Activation Replicator's requeue-on-failure behaviour.
    """
    id: str
    template_id: str
    ne_id: Optional[str]
    params: Dict[str, Any]
    state: ActivationState
    current_step: Optional[str]
    error: Optional[str]
    attempts: int
    created_at: float
    updated_at: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "template_id": self.template_id,
            "ne_id": self.ne_id,
            "params": self.params,
            "state": self.state.value if isinstance(self.state, ActivationState) else self.state,
            "current_step": self.current_step,
            "error": self.error,
            "attempts": self.attempts,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "Activation":
        return Activation(
            id=row["id"],
            template_id=row["template_id"],
            ne_id=row["ne_id"],
            params=json.loads(row["params"]),
            state=ActivationState(row["state"]),
            current_step=row["current_step"],
            error=row["error"],
            attempts=row["attempts"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class NetworkElement:
    """
    A managed network element that activations can target. In a real
    deployment this would represent a physical/virtual peer device;
    here it is a simulated endpoint used to demonstrate multi-NE
    orchestration from a single EDA VNE instance.

    ``blocked`` mirrors the CUDB Activation Blocker: while true, new
    activations targeting this NE are created in the HELD state instead
    of running immediately, and are resumed automatically on unblock.
    """
    id: str
    name: str
    ne_type: str
    management_ip: str
    status: NetworkElementStatus
    blocked: bool
    metadata: Dict[str, Any]
    created_at: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "ne_type": self.ne_type,
            "management_ip": self.management_ip,
            "status": self.status.value if isinstance(self.status, NetworkElementStatus) else self.status,
            "blocked": self.blocked,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "NetworkElement":
        return NetworkElement(
            id=row["id"],
            name=row["name"],
            ne_type=row["ne_type"],
            management_ip=row["management_ip"],
            status=NetworkElementStatus(row["status"]),
            blocked=bool(row["blocked"]),
            metadata=json.loads(row["metadata"]),
            created_at=row["created_at"],
        )


@dataclass
class Alarm:
    """
    A fault-management alarm, raised by the engine when an activation
    finally fails (after any configured auto-retries are exhausted).
    This is the EDA equivalent of the Alarm Handler's fault-to-alarm
    mapping - kept distinct from Activation.error so operators have a
    dedicated, clearable fault list instead of digging through jobs.
    """
    id: str
    severity: AlarmSeverity
    source: str
    text: str
    raised_at: float
    cleared_at: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity.value if isinstance(self.severity, AlarmSeverity) else self.severity,
            "source": self.source,
            "text": self.text,
            "raised_at": self.raised_at,
            "cleared_at": self.cleared_at,
        }

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "Alarm":
        return Alarm(
            id=row["id"],
            severity=AlarmSeverity(row["severity"]),
            source=row["source"],
            text=row["text"],
            raised_at=row["raised_at"],
            cleared_at=row["cleared_at"],
        )
