"""
Persistence layer for EDA. Uses SQLite so the VNE survives restarts
without requiring an external database - handy for a self-contained
virtual network element image.

Also holds the in-process "target mutex" (mirrors the Mutex Handler
microservice in the real Ericsson EDA): a lightweight in-memory lock
keyed by network-element id, preventing two activations from being
provisioned concurrently against the same target. This intentionally
lives in memory (not SQLite) since it only needs to be correct for the
lifetime of this single process.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from eda.core.models import (
    Activation,
    ActivationState,
    Alarm,
    AlarmSeverity,
    NetworkElement,
    NetworkElementStatus,
    ServiceTemplate,
    new_id,
    now,
)

_UNSET = object()

SCHEMA = """
CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    description TEXT NOT NULL,
    steps TEXT NOT NULL,
    parameters_schema TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS network_elements (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    ne_type TEXT NOT NULL,
    management_ip TEXT NOT NULL,
    status TEXT NOT NULL,
    blocked INTEGER NOT NULL DEFAULT 0,
    metadata TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS activations (
    id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    ne_id TEXT,
    params TEXT NOT NULL,
    state TEXT NOT NULL,
    current_step TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS activation_logs (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    activation_id TEXT NOT NULL,
    ts REAL NOT NULL,
    message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alarms (
    id TEXT PRIMARY KEY,
    severity TEXT NOT NULL,
    source TEXT NOT NULL,
    text TEXT NOT NULL,
    raised_at REAL NOT NULL,
    cleared_at REAL
);
"""


class Store:
    """Thread-safe SQLite-backed store for templates, NEs and activations."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

        # In-memory target mutex (Mutex Handler equivalent). Not persisted:
        # a process restart naturally releases all locks.
        self._targets_lock = threading.Lock()
        self._busy_targets: set = set()

    # ---------------------------------------------------------------- #
    # Target mutex (Mutex Handler equivalent)
    # ---------------------------------------------------------------- #
    def try_acquire_target(self, target: str) -> bool:
        """Attempt to reserve exclusive access to a target (NE id, or
        'self' for un-targeted activations). Returns False if another
        activation is already in flight against the same target - the
        caller should reject the request, mirroring the real Mutex
        Handler ('first request acquires lock, others rejected')."""
        with self._targets_lock:
            if target in self._busy_targets:
                return False
            self._busy_targets.add(target)
            return True

    def release_target(self, target: str) -> None:
        with self._targets_lock:
            self._busy_targets.discard(target)

    def is_target_busy(self, target: str) -> bool:
        with self._targets_lock:
            return target in self._busy_targets

    # ---------------------------------------------------------------- #
    # Templates
    # ---------------------------------------------------------------- #
    def create_template(
        self,
        name: str,
        version: str,
        description: str,
        steps: List[str],
        parameters_schema: Optional[Dict[str, Any]] = None,
    ) -> ServiceTemplate:
        tpl = ServiceTemplate(
            id=new_id("tpl"),
            name=name,
            version=version,
            description=description,
            steps=steps,
            parameters_schema=parameters_schema or {},
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO templates (id, name, version, description, steps, "
                "parameters_schema, created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    tpl.id,
                    tpl.name,
                    tpl.version,
                    tpl.description,
                    json.dumps(tpl.steps),
                    json.dumps(tpl.parameters_schema),
                    tpl.created_at,
                ),
            )
            self._conn.commit()
        return tpl

    def get_template(self, template_id: str) -> Optional[ServiceTemplate]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM templates WHERE id = ?", (template_id,)
            ).fetchone()
        return ServiceTemplate.from_row(row) if row else None

    def list_templates(self) -> List[ServiceTemplate]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM templates ORDER BY created_at DESC"
            ).fetchall()
        return [ServiceTemplate.from_row(r) for r in rows]

    def delete_template(self, template_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
            self._conn.commit()
        return cur.rowcount > 0

    # ---------------------------------------------------------------- #
    # Network elements
    # ---------------------------------------------------------------- #
    def create_ne(
        self,
        name: str,
        ne_type: str,
        management_ip: str,
        metadata: Optional[Dict[str, Any]] = None,
        status: NetworkElementStatus = NetworkElementStatus.UNKNOWN,
        blocked: bool = False,
    ) -> NetworkElement:
        ne = NetworkElement(
            id=new_id("ne"),
            name=name,
            ne_type=ne_type,
            management_ip=management_ip,
            status=status,
            blocked=blocked,
            metadata=metadata or {},
            created_at=now(),
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO network_elements (id, name, ne_type, management_ip, "
                "status, blocked, metadata, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    ne.id,
                    ne.name,
                    ne.ne_type,
                    ne.management_ip,
                    ne.status.value,
                    int(ne.blocked),
                    json.dumps(ne.metadata),
                    ne.created_at,
                ),
            )
            self._conn.commit()
        return ne

    def get_ne(self, ne_id: str) -> Optional[NetworkElement]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM network_elements WHERE id = ?", (ne_id,)
            ).fetchone()
        return NetworkElement.from_row(row) if row else None

    def list_ne(self) -> List[NetworkElement]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM network_elements ORDER BY created_at DESC"
            ).fetchall()
        return [NetworkElement.from_row(r) for r in rows]

    def delete_ne(self, ne_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM network_elements WHERE id = ?", (ne_id,))
            self._conn.commit()
        return cur.rowcount > 0

    def update_ne_status(self, ne_id: str, status: NetworkElementStatus) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE network_elements SET status = ? WHERE id = ?",
                (status.value, ne_id),
            )
            self._conn.commit()

    def set_ne_blocked(self, ne_id: str, blocked: bool) -> Optional[NetworkElement]:
        with self._lock:
            self._conn.execute(
                "UPDATE network_elements SET blocked = ? WHERE id = ?",
                (int(blocked), ne_id),
            )
            self._conn.commit()
        return self.get_ne(ne_id)

    # ---------------------------------------------------------------- #
    # Activations
    # ---------------------------------------------------------------- #
    def create_activation(
        self,
        template_id: str,
        ne_id: Optional[str],
        params: Dict[str, Any],
        initial_state: ActivationState = ActivationState.CREATED,
    ) -> Activation:
        act = Activation(
            id=new_id("act"),
            template_id=template_id,
            ne_id=ne_id,
            params=params,
            state=initial_state,
            current_step=None,
            error=None,
            attempts=0,
            created_at=now(),
            updated_at=now(),
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO activations (id, template_id, ne_id, params, state, "
                "current_step, error, attempts, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    act.id,
                    act.template_id,
                    act.ne_id,
                    json.dumps(act.params),
                    act.state.value,
                    act.current_step,
                    act.error,
                    act.attempts,
                    act.created_at,
                    act.updated_at,
                ),
            )
            self._conn.commit()
        return act

    def get_activation(self, activation_id: str) -> Optional[Activation]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM activations WHERE id = ?", (activation_id,)
            ).fetchone()
        return Activation.from_row(row) if row else None

    def list_activations(self) -> List[Activation]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM activations ORDER BY created_at DESC"
            ).fetchall()
        return [Activation.from_row(r) for r in rows]

    def list_held_activations(self, ne_id: str) -> List[Activation]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM activations WHERE ne_id = ? AND state = ? "
                "ORDER BY created_at ASC",
                (ne_id, ActivationState.HELD.value),
            ).fetchall()
        return [Activation.from_row(r) for r in rows]

    def update_activation(
        self,
        activation_id: str,
        state: Optional[ActivationState] = None,
        current_step: Any = _UNSET,
        error: Optional[str] = None,
        clear_error: bool = False,
        attempts: Any = _UNSET,
    ) -> Optional[Activation]:
        act = self.get_activation(activation_id)
        if act is None:
            return None
        new_state = state.value if state else act.state.value
        new_step = act.current_step if current_step is _UNSET else current_step
        new_error = None if clear_error else (error if error is not None else act.error)
        new_attempts = act.attempts if attempts is _UNSET else attempts
        with self._lock:
            self._conn.execute(
                "UPDATE activations SET state=?, current_step=?, error=?, attempts=?, "
                "updated_at=? WHERE id=?",
                (new_state, new_step, new_error, new_attempts, now(), activation_id),
            )
            self._conn.commit()
        return self.get_activation(activation_id)

    def delete_activation(self, activation_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM activations WHERE id = ?", (activation_id,))
            self._conn.execute(
                "DELETE FROM activation_logs WHERE activation_id = ?", (activation_id,)
            )
            self._conn.commit()
        return cur.rowcount > 0

    # ---------------------------------------------------------------- #
    # Activation logs
    # ---------------------------------------------------------------- #
    def append_log(self, activation_id: str, message: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO activation_logs (activation_id, ts, message) VALUES (?,?,?)",
                (activation_id, now(), message),
            )
            self._conn.commit()

    def get_logs(self, activation_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, message FROM activation_logs WHERE activation_id = ? "
                "ORDER BY seq ASC",
                (activation_id,),
            ).fetchall()
        return [{"ts": r["ts"], "message": r["message"]} for r in rows]

    # ---------------------------------------------------------------- #
    # Alarms (Alarm Handler equivalent)
    # ---------------------------------------------------------------- #
    def raise_alarm(self, severity: AlarmSeverity, source: str, text: str) -> Alarm:
        alarm = Alarm(
            id=new_id("alarm"),
            severity=severity,
            source=source,
            text=text,
            raised_at=now(),
            cleared_at=None,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO alarms (id, severity, source, text, raised_at, cleared_at) "
                "VALUES (?,?,?,?,?,?)",
                (alarm.id, alarm.severity.value, alarm.source, alarm.text, alarm.raised_at, None),
            )
            self._conn.commit()
        return alarm

    def list_alarms(self, active_only: bool = False) -> List[Alarm]:
        with self._lock:
            if active_only:
                rows = self._conn.execute(
                    "SELECT * FROM alarms WHERE cleared_at IS NULL ORDER BY raised_at DESC"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM alarms ORDER BY raised_at DESC"
                ).fetchall()
        return [Alarm.from_row(r) for r in rows]

    def get_alarm(self, alarm_id: str) -> Optional[Alarm]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM alarms WHERE id = ?", (alarm_id,)).fetchone()
        return Alarm.from_row(row) if row else None

    def clear_alarm(self, alarm_id: str) -> Optional[Alarm]:
        with self._lock:
            self._conn.execute(
                "UPDATE alarms SET cleared_at = ? WHERE id = ? AND cleared_at IS NULL",
                (now(), alarm_id),
            )
            self._conn.commit()
        return self.get_alarm(alarm_id)


_store_instance: Optional[Store] = None
_store_lock = threading.Lock()


def get_store(db_path: Optional[str] = None) -> Store:
    """Process-wide singleton accessor, used by the FastAPI dependency layer."""
    global _store_instance
    with _store_lock:
        if _store_instance is None:
            from eda.config import settings

            _store_instance = Store(db_path or settings.DB_PATH)
        return _store_instance


def reset_store() -> None:
    """Test helper: drop the singleton so a fresh Store can be created."""
    global _store_instance
    with _store_lock:
        _store_instance = None
