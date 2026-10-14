"""Signing in and out with a password."""

from fastapi import APIRouter, HTTPException, Request, Response, status

from api.config import ApiSettings
from api.dependencies import DatabaseDependency, SessionHolderDependency, SettingsDependency
from api.schemas.auth import (
    NewPasswordRequest,
    PasswordRefusedResponse,
    SignInRefused,
    SignInRefusedResponse,
    SignInRequest,
)
from api.schemas.sessions import SessionResponse
from api.services import sign_in as signing_in
from api.services.sessions import PasswordRefused, replace_temporary_password
from api.services.sessions import sign_out as end_session
from api.services.sign_in import SignedIn

router = APIRouter(prefix="/auth", tags=["auth"])

HOUR = 3600


def set_session_cookie(response: Response, settings: ApiSettings, signed_in: SignedIn) -> None:
    """The session's cookie, lasting no longer than the server honours the session."""
    response.set_cookie(
        settings.session_cookie_name,
        signed_in.cookie,
        max_age=signed_in.max_hours * HOUR,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.post("/sign-in", responses={status.HTTP_401_UNAUTHORIZED: {"model": SignInRefusedResponse}})
async def sign_in(
    body: SignInRequest,
    request: Request,
    response: Response,
    database: DatabaseDependency,
    settings: SettingsDependency,
) -> SessionResponse:
    try:
        signed_in = await signing_in.sign_in(
            database, body.username, body.password, request.headers.get("user-agent")
        )
    except signing_in.SignInRefused as refused:
        detail = SignInRefused.model_validate(refused, from_attributes=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=detail.model_dump(mode="json")
        ) from refused
    set_session_cookie(response, settings, signed_in)
    return SessionResponse.model_validate(signed_in.user, from_attributes=True)


@router.post("/sign-out", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out(
    request: Request, response: Response, database: DatabaseDependency, settings: SettingsDependency
) -> None:
    await end_session(database, request.cookies.get(settings.session_cookie_name))
    response.delete_cookie(
        settings.session_cookie_name, path="/", secure=settings.session_cookie_secure, httponly=True
    )


@router.post(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_409_CONFLICT: {"model": PasswordRefusedResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": PasswordRefusedResponse},
    },
)
async def change_password(
    body: NewPasswordRequest, user: SessionHolderDependency, database: DatabaseDependency
) -> None:
    """Replace the temporary password an admin set with one the person chooses."""
    try:
        await replace_temporary_password(database, user, body.password)
    except PasswordRefused as refused:
        due = refused.reason != "no_change_due"
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT if due else status.HTTP_409_CONFLICT,
            detail=refused.reason,
        ) from refused
