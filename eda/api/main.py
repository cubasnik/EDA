"""
FastAPI application factory for the EDA northbound API.

Endpoint summary (see /docs for full OpenAPI spec once running):

    GET    /health
    GET    /version
    GET    /metrics                       (unauthenticated, Prometheus format)

    POST   /templates
    GET    /templates
    GET    /templates/{id}
    DELETE /templates/{id}

    POST   /network-elements
    GET    /network-elements
    GET    /network-elements/{id}
    DELETE /network-elements/{id}
    POST   /network-elements/{id}/block
    POST   /network-elements/{id}/unblock

    POST   /activations
    POST   /activations/batch
    GET    /activations
    GET    /activations/{id}
    GET    /activations/{id}/status
    GET    /activations/{id}/logs
    POST   /activations/{id}/deactivate
    POST   /activations/{id}/retry
    DELETE /activations/{id}

    GET    /alarms
    POST   /alarms/{id}/clear

If EDA_API_KEY is set, every endpoint above except /health, /version and
/metrics requires a matching 'X-API-Key' header (see eda/api/security.py).
"""
from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse

from eda import __version__
from eda.api.routers import activations, alarms, health, metrics, network_elements, templates
from eda.api.security import verify_api_key


def create_app() -> FastAPI:
    app = FastAPI(
        title="EDA - Enhanced Dynamic Activation",
        description=(
            "Northbound REST API of the EDA virtual network element. "
            "Provides dynamic service-activation orchestration on top of a "
            "simulated network element, deployable on OpenStack."
        ),
        version=__version__,
    )

    # Unauthenticated: liveness/readiness and monitoring surfaces.
    app.include_router(health.router)
    app.include_router(metrics.router)

    # AAA-gated (no-op unless EDA_API_KEY is set): the actual EDA services.
    auth = [Depends(verify_api_key)]
    app.include_router(templates.router, dependencies=auth)
    app.include_router(network_elements.router, dependencies=auth)
    app.include_router(activations.router, dependencies=auth)
    app.include_router(alarms.router, dependencies=auth)

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse(url="/docs")

    return app


app = create_app()
