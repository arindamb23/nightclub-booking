"""Start the backend: ``python -m app`` (host/port come from the project .env only)."""
import uvicorn

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
