"""Whether the service is up, and whether it can serve from its database."""

from fastapi import APIRouter, Response, status

from api.dependencies import DatabaseDependency
from api.schemas.health import HealthResponse, ReadinessResponse
from api.services.readiness import EXPECTED_REVISION, check_readiness

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}})
async def ready(database: DatabaseDependency, response: Response) -> ReadinessResponse:
    readiness = await check_readiness(database)
    if not readiness.is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if readiness.is_ready else "not_ready",
        database_schema=readiness.schema,
        migration=readiness.revision,
        expected_migration=EXPECTED_REVISION,
        reason=readiness.reason,
    )
