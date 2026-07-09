from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from eda.api.deps import store_dep
from eda.api.schemas import AlarmResponse
from eda.core.store import Store

router = APIRouter(prefix="/alarms", tags=["alarms"])


@router.get("", response_model=List[AlarmResponse])
def list_alarms(
    active: bool = Query(default=False, description="If true, only return uncleared alarms"),
    store: Store = Depends(store_dep),
):
    return [a.to_dict() for a in store.list_alarms(active_only=active)]


@router.post("/{alarm_id}/clear", response_model=AlarmResponse)
def clear_alarm(alarm_id: str, store: Store = Depends(store_dep)):
    if store.get_alarm(alarm_id) is None:
        raise HTTPException(status_code=404, detail=f"Alarm '{alarm_id}' not found")
    alarm = store.clear_alarm(alarm_id)
    return alarm.to_dict()
