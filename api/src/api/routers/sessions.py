"""The person a request acts for."""

from fastapi import APIRouter, status

from api.dependencies import SessionHolderDependency
from api.schemas.sessions import NotSignedInResponse, SessionResponse

router = APIRouter(tags=["sessions"])


@router.get("/session", responses={status.HTTP_401_UNAUTHORIZED: {"model": NotSignedInResponse}})
async def session(user: SessionHolderDependency) -> SessionResponse:
    return SessionResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        must_change_password=user.must_change_password,
    )
