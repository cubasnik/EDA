from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from eda.api.deps import engine_dep, store_dep
from eda.api.schemas import NetworkElementCreateRequest, NetworkElementResponse
from eda.core.engine import ActivationEngine
from eda.core.models import NetworkElementStatus
from eda.core.store import Store

router = APIRouter(prefix="/network-elements", tags=["network-elements"])


@router.post("", response_model=NetworkElementResponse, status_code=201)
def register_ne(body: NetworkElementCreateRequest, store: Store = Depends(store_dep)):
    ne = store.create_ne(
        name=body.name,
        ne_type=body.ne_type,
        management_ip=body.management_ip,
        metadata=body.metadata,
        status=NetworkElementStatus.REACHABLE,
    )
    return ne.to_dict()


@router.get("", response_model=List[NetworkElementResponse])
def list_ne(store: Store = Depends(store_dep)):
    return [n.to_dict() for n in store.list_ne()]


@router.get("/{ne_id}", response_model=NetworkElementResponse)
def get_ne(ne_id: str, store: Store = Depends(store_dep)):
    ne = store.get_ne(ne_id)
    if ne is None:
        raise HTTPException(status_code=404, detail=f"Network element '{ne_id}' not found")
    return ne.to_dict()


@router.delete("/{ne_id}", status_code=204)
def delete_ne(ne_id: str, store: Store = Depends(store_dep)):
    if not store.delete_ne(ne_id):
        raise HTTPException(status_code=404, detail=f"Network element '{ne_id}' not found")
    return None


@router.post("/{ne_id}/block", response_model=NetworkElementResponse)
def block_ne(ne_id: str, store: Store = Depends(store_dep)):
    """Put an NE into maintenance mode (CUDB Activation Blocker equivalent).
    New activations targeting this NE will be created HELD instead of
    running immediately; activations already in progress are unaffected."""
    if store.get_ne(ne_id) is None:
        raise HTTPException(status_code=404, detail=f"Network element '{ne_id}' not found")
    ne = store.set_ne_blocked(ne_id, True)
    return ne.to_dict()


@router.post("/{ne_id}/unblock", response_model=NetworkElementResponse)
def unblock_ne(
    ne_id: str,
    background_tasks: BackgroundTasks,
    store: Store = Depends(store_dep),
    engine: ActivationEngine = Depends(engine_dep),
):
    """Take an NE out of maintenance mode and resume any activations that
    were HELD while it was blocked."""
    if store.get_ne(ne_id) is None:
        raise HTTPException(status_code=404, detail=f"Network element '{ne_id}' not found")
    ne = store.set_ne_blocked(ne_id, False)
    for held in store.list_held_activations(ne_id):
        background_tasks.add_task(engine.resume_held_activation, held.id)
    return ne.to_dict()
