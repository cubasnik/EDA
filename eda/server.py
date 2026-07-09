"""Entry point that launches the EDA API server (uvicorn)."""
import uvicorn

from eda.config import settings


def main() -> None:
    uvicorn.run(
        "eda.api.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
