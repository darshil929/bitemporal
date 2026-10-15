"""What admins alone read."""

from fastapi import APIRouter, status

from api.dependencies import AdminDependency, DatabaseDependency
from api.schemas.audit import AuditEntryResponse
from api.schemas.sessions import NotSignedInResponse
from api.services.audit import recent_admin_actions

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    responses={status.HTTP_401_UNAUTHORIZED: {"model": NotSignedInResponse}},
)


@router.get("/audit")
async def admin_actions(
    admin: AdminDependency, database: DatabaseDependency
) -> list[AuditEntryResponse]:
    """The newest admin actions, newest first."""
    entries = await recent_admin_actions(database, admin.id)
    return [AuditEntryResponse.model_validate(entry) for entry in entries]
