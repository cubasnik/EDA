"""
Minimal AAA (Authentication/Authorization) dependency - the EDA
equivalent of the eric-act-aaa microservice, reduced to a single shared
secret since this project has no user/role model. Applied to the
templates/network-elements/activations routers in eda/api/main.py;
/health and /metrics stay open so liveness checks and Prometheus
scraping keep working without credentials.
"""
from fastapi import Header, HTTPException

from eda.config import settings


def verify_api_key(x_api_key: str = Header(default="")) -> None:
    if not settings.API_KEY:
        # Auth disabled (default) - local/dev convenience.
        return
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Missing or invalid API key")
