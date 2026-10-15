"""What admins alone read and change."""

from fastapi import APIRouter, HTTPException, status

from api.dependencies import AdminDependency, DatabaseDependency
from api.schemas.audit import AuditEntryResponse
from api.schemas.people import (
    AddedPersonResponse,
    NewPersonRequest,
    PersonRefusedResponse,
    PersonResponse,
)
from api.schemas.sessions import NotSignedInResponse
from api.services import people as managing
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


@router.get("/users")
async def people(admin: AdminDependency, database: DatabaseDependency) -> list[PersonResponse]:
    """Every account, newest first."""
    found = await managing.people(database, admin.id)
    return [PersonResponse.model_validate(person) for person in found]


@router.post(
    "/users",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"model": PersonRefusedResponse}},
)
async def add_person(
    body: NewPersonRequest, admin: AdminDependency, database: DatabaseDependency
) -> AddedPersonResponse:
    """Add a person, with a temporary password they replace at first sign-in."""
    try:
        added = await managing.add_person(
            database, admin.id, body.username, body.display_name, body.role
        )
    except managing.PersonRefused as refused:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=refused.reason
        ) from refused
    return AddedPersonResponse.model_validate(added)
