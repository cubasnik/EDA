"""
Runtime configuration for the EDA virtual network element.
All values can be overridden via environment variables, which makes the
element easy to parameterize from an OpenStack Heat template / cloud-init.
"""
import os


class Settings:
    # Identity of this network element instance
    NE_NAME: str = os.environ.get("EDA_NE_NAME", "eda-vne-01")
    NE_TYPE: str = os.environ.get("EDA_NE_TYPE", "virtual-network-element")

    # API server
    API_HOST: str = os.environ.get("EDA_API_HOST", "0.0.0.0")
    API_PORT: int = int(os.environ.get("EDA_API_PORT", "8080"))

    # Storage
    DB_PATH: str = os.environ.get("EDA_DB_PATH", os.path.join(os.getcwd(), "eda.db"))

    # Simulated workflow timing (seconds)
    STEP_MIN_DELAY: float = float(os.environ.get("EDA_STEP_MIN_DELAY", "0.4"))
    STEP_MAX_DELAY: float = float(os.environ.get("EDA_STEP_MAX_DELAY", "1.2"))

    # CLI defaults
    API_URL: str = os.environ.get("EDA_API_URL", "http://localhost:8080")

    # AAA (Security & Connectivity equivalent). When unset (default),
    # the API requires no authentication - convenient for local dev, but
    # NOT recommended for anything reachable outside a trusted network.
    # Set EDA_API_KEY to enable a simple shared-secret check on all
    # /templates, /network-elements and /activations endpoints (clients
    # send it back as the 'X-API-Key' header).
    API_KEY: str = os.environ.get("EDA_API_KEY", "")


settings = Settings()
