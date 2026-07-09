from typing import List

from fastapi import APIRouter, Depends, HTTPException

from eda.api.deps import store_dep
from eda.api.schemas import TemplateCreateRequest, TemplateResponse
from eda.core.store import Store

router = APIRouter(prefix="/templates", tags=["templates"])


@router.post("", response_model=TemplateResponse, status_code=201)
def create_template(body: TemplateCreateRequest, store: Store = Depends(store_dep)):
    tpl = store.create_template(
        name=body.name,
        version=body.version,
        description=body.description,
        steps=body.steps,
        parameters_schema=body.parameters_schema,
    )
    return tpl.to_dict()


@router.get("", response_model=List[TemplateResponse])
def list_templates(store: Store = Depends(store_dep)):
    return [t.to_dict() for t in store.list_templates()]


@router.get("/{template_id}", response_model=TemplateResponse)
def get_template(template_id: str, store: Store = Depends(store_dep)):
    tpl = store.get_template(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    return tpl.to_dict()


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: str, store: Store = Depends(store_dep)):
    if not store.delete_template(template_id):
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    return None
