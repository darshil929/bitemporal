"""Signing in and out with a password."""

from fastapi import APIRouter, HTTPException, Request, Response, status

from api.dependencies import DatabaseDependency, SettingsDependency
from api.schemas.auth import SignInRefused, SignInRefusedResponse, SignInRequest
from api.schemas.sessions import SessionResponse
from api.services import sign_in as signing_in
from api.services.sessions import sign_out as end_session

router = APIRouter(prefix="/auth", tags=["auth"])

HOUR = 3600


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
    # The cookie lasts no longer than the server honours the session.
    response.set_cookie(
        settings.session_cookie_name,
        signed_in.cookie,
        max_age=signed_in.max_hours * HOUR,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return SessionResponse.model_validate(signed_in.user, from_attributes=True)


@router.post("/sign-out", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out(
    request: Request, response: Response, database: DatabaseDependency, settings: SettingsDependency
) -> None:
    await end_session(database, request.cookies.get(settings.session_cookie_name))
    response.delete_cookie(
        settings.session_cookie_name, path="/", secure=settings.session_cookie_secure, httponly=True
    )
