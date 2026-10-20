"""Entry point for uvicorn: `uvicorn nexora.api.main:app`."""

from nexora.api.app import create_app

app = create_app()
