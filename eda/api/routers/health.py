import time

from fastapi import APIRouter

from eda import __version__
from eda.api.schemas import HealthResponse
from eda.config import settings

router = APIRouter(tags=["health"])

_START_TIME = time.time()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="UP",
        ne_name=settings.NE_NAME,
        ne_type=settings.NE_TYPE,
        version=__version__,
        uptime_seconds=round(time.time() - _START_TIME, 2),
    )


@router.get("/version")
def version() -> dict:
    return {"product": "EDA (Enhanced Dynamic Activation)", "version": __version__}
