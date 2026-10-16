"""What admins alone read and change."""

from typing import Any

from fastapi import APIRouter, HTTPException, status

from api.dependencies import AdminDependency, DatabaseDependency
from api.schemas.audit import AuditEntryResponse
from api.schemas.session_limit_settings import SessionLimitsChangeRequest, SessionLimitsResponse
from api.schemas.sessions import NotSignedInResponse
from api.schemas.user_management import (
    AccountChangeRequest,
    IssuedPasswordResponse,
    NewPersonRequest,
    PersonRefusedResponse,
    PersonResponse,
)
from api.services import session_limit_settings, user_management
from api.services.audit import recent_admin_actions

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    responses={status.HTTP_401_UNAUTHORIZED: {"model": NotSignedInResponse}},
)

# An account the API does not hold answers 404; every other refusal 409.
REFUSED_AS = {"person_not_found": status.HTTP_404_NOT_FOUND}
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": PersonRefusedResponse}
}
CONFLICT: dict[int | str, dict[str, Any]] = {
    status.HTTP_409_CONFLICT: {"model": PersonRefusedResponse}
}


def refusal(refused: user_management.PersonRefused) -> HTTPException:
    code = REFUSED_AS.get(refused.reason, status.HTTP_409_CONFLICT)
    return HTTPException(status_code=code, detail=refused.reason)


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
    found = await user_management.people(database, admin.id)
    return [PersonResponse.model_validate(person) for person in found]


@router.post("/users", status_code=status.HTTP_201_CREATED, responses=CONFLICT)
async def add_person(
    body: NewPersonRequest, admin: AdminDependency, database: DatabaseDependency
) -> IssuedPasswordResponse:
    """Add a person, with a temporary password they replace at first sign-in."""
    try:
        added = await user_management.add_person(
            database, admin.id, body.username, body.display_name, body.role
        )
    except user_management.PersonRefused as refused:
        raise refusal(refused) from refused
    return IssuedPasswordResponse.model_validate(added)


@router.patch("/users/{person_id}", responses=NOT_FOUND | CONFLICT)
async def change_account(
    person_id: int, body: AccountChangeRequest, admin: AdminDependency, database: DatabaseDependency
) -> PersonResponse:
    """Change an account's role or whether it is disabled."""
    try:
        changed = await user_management.change_account(
            database, admin.id, person_id, body.role, body.disabled
        )
    except user_management.PersonRefused as refused:
        raise refusal(refused) from refused
    return PersonResponse.model_validate(changed)


@router.post("/users/{person_id}/password", responses=NOT_FOUND)
async def reset_password(
    person_id: int, admin: AdminDependency, database: DatabaseDependency
) -> IssuedPasswordResponse:
    """Replace an account's password with a temporary one, ending its sessions."""
    try:
        issued = await user_management.reset_password(database, admin.id, person_id)
    except user_management.PersonRefused as refused:
        raise refusal(refused) from refused
    return IssuedPasswordResponse.model_validate(issued)


@router.get("/settings")
async def session_limits(
    admin: AdminDependency, database: DatabaseDependency
) -> SessionLimitsResponse:
    """The session limits in force for everyone."""
    limits = await session_limit_settings.session_limits(database, admin.id)
    return SessionLimitsResponse.model_validate(limits)


@router.patch("/settings")
async def change_session_limits(
    body: SessionLimitsChangeRequest, admin: AdminDependency, database: DatabaseDependency
) -> SessionLimitsResponse:
    """Set the idle limit, the maximum, or both; running sessions are held to them at once."""
    limits = await session_limit_settings.change_session_limits(
        database, admin.id, body.session_idle_minutes, body.session_max_hours
    )
    return SessionLimitsResponse.model_validate(limits)
