"""FastAPI application entry point."""

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Bitemporal API", version="0.0.0")


class HealthResponse(BaseModel):
    status: str


@app.get("/health")
def health() -> HealthResponse:
    return HealthResponse(status="ok")
