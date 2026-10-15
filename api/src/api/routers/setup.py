"""The first-run setup: whether an admin exists, and the first one."""

from fastapi import APIRouter, HTTPException, Request, Response, status

from api.dependencies import DatabaseDependency, SettingsDependency
from api.routers.auth import set_session_cookie
from api.schemas.first_admin_setup import FirstAdminRequest, SetupRefusedResponse, SetupResponse
from api.schemas.sessions import SessionResponse
from api.services import first_admin_setup

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get("")
async def setup(database: DatabaseDependency) -> SetupResponse:
    return SetupResponse(admin_exists=await first_admin_setup.admin_exists(database))


@router.post(
    "/admin",
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_409_CONFLICT: {"model": SetupRefusedResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": SetupRefusedResponse},
    },
)
async def create_first_admin(
    body: FirstAdminRequest,
    request: Request,
    response: Response,
    database: DatabaseDependency,
    settings: SettingsDependency,
) -> SessionResponse:
    try:
        signed_in = await first_admin_setup.create_first_admin(
            database,
            body.username,
            body.display_name,
            body.password,
            request.headers.get("user-agent"),
        )
    except first_admin_setup.SetupRefused as refused:
        conflict = refused.reason == "admin_exists"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT
            if conflict
            else status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=refused.reason,
        ) from refused
    set_session_cookie(response, settings, signed_in)
    return SessionResponse.model_validate(signed_in.user, from_attributes=True)
