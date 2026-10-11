"""Whether the service is up."""

from fastapi import APIRouter

from api.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> HealthResponse:
    return HealthResponse(status="ok")
