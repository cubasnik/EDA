"""
Simulated dynamic-activation workflow engine.

This is the heart of EDA: it drives an Activation through its state
machine by "executing" each step of the associated ServiceTemplate.
No real network configuration is performed - each step is simulated
with a short delay and a log entry, which is enough to demonstrate the
orchestration model (and is easy to swap for real NETCONF/SSH/Ansible
drivers later, see docs/ARCHITECTURE.md).

State machine:

    CREATED -> VALIDATING -> ACTIVATING -> ACTIVE
       ^                          |
       |                          v
     (unblock)                  FAILED --(auto/manual retry)--> VALIDATING
       |
     HELD  (created while target NE is blocked; resumed on unblock)

    ACTIVE  -> DEACTIVATING -> DEACTIVATED
    FAILED  -> DEACTIVATING -> DEACTIVATED

Several cross-cutting behaviours mirror real Ericsson EDA microservices:

- Target mutex (Mutex Handler): callers must reserve the target via
  ``store.try_acquire_target()`` *before* scheduling engine work; this
  module always releases that reservation exactly once, in a ``finally``
  block, when the workflow reaches a terminal state.
- Fault -> alarm mapping (Alarm Handler), best-effort webhook
  notification (Inbound Async) and PM metrics (PM Server) all happen
  once the workflow is done, regardless of whether it ended via
  run_activation/run_deactivation.
"""
from __future__ import annotations

import random
import time
from typing import Optional

import requests

from eda.config import settings
from eda.core import metrics
from eda.core.models import ActivationState, AlarmSeverity
from eda.core.store import Store


class TemplateNotFound(Exception):
    pass


class InvalidStateTransition(Exception):
    pass


class ActivationEngine:
    def __init__(self, store: Store):
        self.store = store

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _delay(self) -> None:
        time.sleep(random.uniform(settings.STEP_MIN_DELAY, settings.STEP_MAX_DELAY))

    def _log(self, activation_id: str, message: str) -> None:
        self.store.append_log(activation_id, message)

    def _target_for(self, ne_id: Optional[str]) -> str:
        return ne_id or "self"

    def _step_with_failure_check(
        self, activation_id: str, params: dict, step_name: str
    ) -> None:
        self._log(activation_id, f"Executing step: {step_name}")
        self._delay()
        if params.get("fail_at_step") == step_name:
            raise RuntimeError(f"Simulated failure injected at step '{step_name}'")
        self._log(activation_id, f"Step completed: {step_name}")

    def _raise_failure_alarm(self, activation_id: str, target: str, error: str) -> None:
        alarm = self.store.raise_alarm(
            severity=AlarmSeverity.MAJOR,
            source=target,
            text=f"Activation {activation_id} failed: {error}",
        )
        metrics.ALARMS_RAISED.labels(severity=alarm.severity.value).inc()
        self._log(activation_id, f"Alarm raised: {alarm.id} (severity={alarm.severity.value})")

    def _send_webhook(self, activation_id: str) -> None:
        act = self.store.get_activation(activation_id)
        if act is None:
            return
        webhook_url = act.params.get("webhook_url")
        if not webhook_url:
            return
        try:
            requests.post(webhook_url, json=act.to_dict(), timeout=3)
            self._log(activation_id, f"Webhook notified: {webhook_url}")
        except requests.RequestException as exc:
            self._log(activation_id, f"Webhook notification FAILED ({webhook_url}): {exc}")

    def _record_terminal(self, activation_id: str, state: ActivationState) -> None:
        act = self.store.get_activation(activation_id)
        if act is None:
            return
        metrics.ACTIVATIONS_TERMINAL.labels(state=state.value).inc()
        metrics.ACTIVATION_DURATION.observe(max(0.0, act.updated_at - act.created_at))

    # ------------------------------------------------------------------ #
    # public API - intended to be run in a background task/thread.
    # Callers MUST have already reserved the target via
    # store.try_acquire_target(ne_id or "self") before invoking these.
    # ------------------------------------------------------------------ #
    def run_activation(self, activation_id: str) -> None:
        act = self.store.get_activation(activation_id)
        if act is None:
            return
        target = self._target_for(act.ne_id)
        metrics.ACTIVATIONS_IN_PROGRESS.inc()

        try:
            tpl = self.store.get_template(act.template_id)
            if tpl is None:
                error = f"Template '{act.template_id}' not found"
                self.store.update_activation(activation_id, state=ActivationState.FAILED, error=error)
                self._log(activation_id, f"Activation failed: {error}")
                self._raise_failure_alarm(activation_id, target, error)
                self._record_terminal(activation_id, ActivationState.FAILED)
                return

            auto_retry_cfg = act.params.get("auto_retry") or {}
            max_attempts = max(1, int(auto_retry_cfg.get("max_attempts", 1)))
            backoff = float(auto_retry_cfg.get("backoff_seconds", 1.0))

            attempt = act.attempts
            while True:
                attempt += 1
                self.store.update_activation(activation_id, attempts=attempt)
                self._log(
                    activation_id,
                    f"Starting activation of service '{tpl.name}' (v{tpl.version}) "
                    f"on NE '{target}' (attempt {attempt}/{max_attempts})",
                )
                try:
                    self.store.update_activation(
                        activation_id, state=ActivationState.VALIDATING, current_step="validate_params"
                    )
                    self._step_with_failure_check(activation_id, act.params, "validate_params")

                    self.store.update_activation(activation_id, state=ActivationState.ACTIVATING)
                    for step in tpl.steps:
                        self.store.update_activation(activation_id, current_step=step)
                        self._step_with_failure_check(activation_id, act.params, step)

                    self.store.update_activation(
                        activation_id,
                        state=ActivationState.ACTIVE,
                        current_step=None,
                        clear_error=True,
                    )
                    self._log(activation_id, "Activation completed successfully - service is ACTIVE")
                    self._record_terminal(activation_id, ActivationState.ACTIVE)
                    return

                except Exception as exc:  # noqa: BLE001 - broad on purpose for a simulation engine
                    if attempt < max_attempts:
                        self._log(
                            activation_id,
                            f"Attempt {attempt} failed: {exc}. Auto-retrying in {backoff}s "
                            f"({attempt}/{max_attempts})",
                        )
                        time.sleep(backoff)
                        continue
                    self.store.update_activation(
                        activation_id, state=ActivationState.FAILED, error=str(exc)
                    )
                    self._log(activation_id, f"Activation FAILED after {attempt} attempt(s): {exc}")
                    self._raise_failure_alarm(activation_id, target, str(exc))
                    self._record_terminal(activation_id, ActivationState.FAILED)
                    return
        finally:
            metrics.ACTIVATIONS_IN_PROGRESS.dec()
            self.store.release_target(target)
            self._send_webhook(activation_id)

    def run_deactivation(self, activation_id: str) -> None:
        act = self.store.get_activation(activation_id)
        if act is None:
            return
        target = self._target_for(act.ne_id)
        metrics.ACTIVATIONS_IN_PROGRESS.inc()

        try:
            if act.state not in (ActivationState.ACTIVE, ActivationState.FAILED):
                self._log(
                    activation_id,
                    f"Deactivation refused: invalid current state '{act.state.value}'",
                )
                return

            tpl = self.store.get_template(act.template_id)
            steps = list(reversed(tpl.steps)) if tpl else []

            self.store.update_activation(activation_id, state=ActivationState.DEACTIVATING)
            self._log(activation_id, "Starting deactivation (teardown)")
            try:
                for step in steps:
                    self.store.update_activation(activation_id, current_step=f"teardown:{step}")
                    self._log(activation_id, f"Tearing down step: {step}")
                    self._delay()
                self.store.update_activation(
                    activation_id,
                    state=ActivationState.DEACTIVATED,
                    current_step=None,
                    clear_error=True,
                )
                self._log(activation_id, "Deactivation completed - service is DEACTIVATED")
                self._record_terminal(activation_id, ActivationState.DEACTIVATED)
            except Exception as exc:  # noqa: BLE001
                self.store.update_activation(
                    activation_id, state=ActivationState.FAILED, error=str(exc)
                )
                self._log(activation_id, f"Deactivation FAILED: {exc}")
                self._raise_failure_alarm(activation_id, target, str(exc))
                self._record_terminal(activation_id, ActivationState.FAILED)
        finally:
            metrics.ACTIVATIONS_IN_PROGRESS.dec()
            self.store.release_target(target)
            self._send_webhook(activation_id)

    def retry_activation(self, activation_id: str) -> None:
        """Re-run a FAILED activation from the beginning. The caller must
        have already reserved the target mutex before invoking this -
        run_activation() (called internally) will release it exactly once
        when the retried run reaches a terminal state."""
        act = self.store.get_activation(activation_id)
        if act is None:
            return
        if act.state != ActivationState.FAILED:
            self._log(
                activation_id,
                f"Retry refused: activation is in state '{act.state.value}', not FAILED",
            )
            self.store.release_target(self._target_for(act.ne_id))
            return
        self._log(activation_id, "Retrying activation from the beginning")
        self.store.update_activation(
            activation_id, state=ActivationState.CREATED, current_step=None, clear_error=True
        )
        self.run_activation(activation_id)

    def resume_held_activation(self, activation_id: str) -> None:
        """Resume an activation that was created while its target NE was
        blocked. Called after the NE is unblocked; acquires the target
        mutex itself since, unlike create/deactivate/retry, there is no
        HTTP request in flight to have reserved it beforehand."""
        act = self.store.get_activation(activation_id)
        if act is None or act.state != ActivationState.HELD:
            return
        target = self._target_for(act.ne_id)
        if not self.store.try_acquire_target(target):
            self._log(activation_id, f"Resume deferred: target '{target}' still busy")
            return
        self.store.update_activation(activation_id, state=ActivationState.CREATED)
        self._log(activation_id, "Target unblocked - resuming held activation")
        self.run_activation(activation_id)
