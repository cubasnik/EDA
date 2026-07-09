"""PM Server equivalent: exposes Prometheus-format metrics."""
from fastapi import APIRouter, Response

from eda.core.metrics import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
