from typing import List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from eda.api.deps import engine_dep, store_dep
from eda.api.schemas import (
    ActivationCreateRequest,
    ActivationLogsResponse,
    ActivationResponse,
    BatchActivationCreateRequest,
    BatchActivationItemResult,
)
from eda.core import metrics
from eda.core.engine import ActivationEngine
from eda.core.models import ActivationState
from eda.core.store import Store

router = APIRouter(prefix="/activations", tags=["activations"])


def _create_activation_item(
    body: ActivationCreateRequest,
    background_tasks: BackgroundTasks,
    store: Store,
    engine: ActivationEngine,
) -> Tuple[bool, Optional[dict], Optional[str], int]:
    """Shared logic behind both the single-item and batch create
    endpoints. Returns (ok, activation_dict_or_None, error_or_None,
    http_status) instead of raising, so the batch endpoint can report a
    partial failure per item without aborting the whole batch."""
    tpl = store.get_template(body.template_id)
    if tpl is None:
        return False, None, f"Template '{body.template_id}' not found", 404

    ne = None
    if body.ne_id is not None:
        ne = store.get_ne(body.ne_id)
        if ne is None:
            return False, None, f"Network element '{body.ne_id}' not found", 404

    target = body.ne_id or "self"

    if ne is not None and ne.blocked:
        # CUDB Activation Blocker equivalent: hold instead of running.
        act = store.create_activation(
            template_id=body.template_id,
            ne_id=body.ne_id,
            params=body.params,
            initial_state=ActivationState.HELD,
        )
        store.append_log(act.id, f"Activation held: target NE '{body.ne_id}' is blocked")
        metrics.ACTIVATIONS_CREATED.inc()
        return True, act.to_dict(), None, 202

    if not store.try_acquire_target(target):
        return False, None, f"Target '{target}' is busy processing another activation", 409

    act = store.create_activation(template_id=body.template_id, ne_id=body.ne_id, params=body.params)
    metrics.ACTIVATIONS_CREATED.inc()
    background_tasks.add_task(engine.run_activation, act.id)
    return True, act.to_dict(), None, 202


@router.post("", response_model=ActivationResponse, status_code=202)
def create_activation(
    body: ActivationCreateRequest,
    background_tasks: BackgroundTasks,
    store: Store = Depends(store_dep),
    engine: ActivationEngine = Depends(engine_dep),
):
    ok, data, error, status_code = _create_activation_item(body, background_tasks, store, engine)
    if not ok:
        raise HTTPException(status_code=status_code, detail=error)
    return data


@router.post("/batch", response_model=List[BatchActivationItemResult])
def create_activations_batch(
    body: BatchActivationCreateRequest,
    background_tasks: BackgroundTasks,
    store: Store = Depends(store_dep),
    engine: ActivationEngine = Depends(engine_dep),
):
    """Inbound Batch Handler equivalent: create many activations in one
    call. Each item succeeds or fails independently - a busy target or a
    missing template in one item does not abort the rest of the batch."""
    results = []
    for item in body.activations:
        ok, data, error, _status = _create_activation_item(item, background_tasks, store, engine)
        results.append({"ok": ok, "activation": data, "error": error})
    return results


@router.get("", response_model=List[ActivationResponse])
def list_activations(store: Store = Depends(store_dep)):
    return [a.to_dict() for a in store.list_activations()]


@router.get("/{activation_id}", response_model=ActivationResponse)
def get_activation(activation_id: str, store: Store = Depends(store_dep)):
    act = store.get_activation(activation_id)
    if act is None:
        raise HTTPException(status_code=404, detail=f"Activation '{activation_id}' not found")
    return act.to_dict()


@router.get("/{activation_id}/status", response_model=ActivationResponse)
def get_activation_status(activation_id: str, store: Store = Depends(store_dep)):
    act = store.get_activation(activation_id)
    if act is None:
        raise HTTPException(status_code=404, detail=f"Activation '{activation_id}' not found")
    return act.to_dict()


@router.get("/{activation_id}/logs", response_model=ActivationLogsResponse)
def get_activation_logs(activation_id: str, store: Store = Depends(store_dep)):
    act = store.get_activation(activation_id)
    if act is None:
        raise HTTPException(status_code=404, detail=f"Activation '{activation_id}' not found")
    return {"activation_id": activation_id, "logs": store.get_logs(activation_id)}


@router.post("/{activation_id}/deactivate", response_model=ActivationResponse, status_code=202)
def deactivate_activation(
    activation_id: str,
    background_tasks: BackgroundTasks,
    store: Store = Depends(store_dep),
    engine: ActivationEngine = Depends(engine_dep),
):
    act = store.get_activation(activation_id)
    if act is None:
        raise HTTPException(status_code=404, detail=f"Activation '{activation_id}' not found")
    if act.state not in (ActivationState.ACTIVE, ActivationState.FAILED):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot deactivate an activation in state '{act.state.value}'",
        )
    target = act.ne_id or "self"
    if not store.try_acquire_target(target):
        raise HTTPException(status_code=409, detail=f"Target '{target}' is busy, try again shortly")
    background_tasks.add_task(engine.run_deactivation, activation_id)
    return act.to_dict()


@router.post("/{activation_id}/retry", response_model=ActivationResponse, status_code=202)
def retry_activation(
    activation_id: str,
    background_tasks: BackgroundTasks,
    store: Store = Depends(store_dep),
    engine: ActivationEngine = Depends(engine_dep),
):
    act = store.get_activation(activation_id)
    if act is None:
        raise HTTPException(status_code=404, detail=f"Activation '{activation_id}' not found")
    if act.state != ActivationState.FAILED:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot retry an activation in state '{act.state.value}' (must be FAILED)",
        )
    target = act.ne_id or "self"
    if not store.try_acquire_target(target):
        raise HTTPException(status_code=409, detail=f"Target '{target}' is busy, try again shortly")
    background_tasks.add_task(engine.retry_activation, activation_id)
    return act.to_dict()


@router.delete("/{activation_id}", status_code=204)
def delete_activation(activation_id: str, store: Store = Depends(store_dep)):
    if not store.delete_activation(activation_id):
        raise HTTPException(status_code=404, detail=f"Activation '{activation_id}' not found")
    return None
