"""Local FastAPI HTTP interface implementing the D10 contract (I22)."""

from fastapi import FastAPI

from .server import ApiError, LOOPBACK_HOSTS, create_app, serve_local

app = FastAPI(title="Chuyên đề KTPM – API cục bộ", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


__all__ = ["ApiError", "LOOPBACK_HOSTS", "app", "create_app", "serve_local"]
