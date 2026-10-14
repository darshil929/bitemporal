"""What an endpoint takes from the running application."""

from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status

from api.config import ApiSettings
from api.db.database import Database
from api.schemas.sessions import SessionEnded
from api.services.sessions import NotSignedIn, SignedInUser, signed_in_user


def database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def settings(request: Request) -> ApiSettings:
    return cast(ApiSettings, request.app.state.settings)


DatabaseDependency = Annotated[Database, Depends(database)]
SettingsDependency = Annotated[ApiSettings, Depends(settings)]


async def session_holder(
    request: Request, database: DatabaseDependency, settings: SettingsDependency
) -> SignedInUser:
    """The person the request's session acts for; a request without a running one is refused."""
    try:
        return await signed_in_user(database, request.cookies.get(settings.session_cookie_name))
    except NotSignedIn as refused:
        ended = SessionEnded.model_validate(refused, from_attributes=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ended.model_dump(mode="json")
        ) from refused


SessionHolderDependency = Annotated[SignedInUser, Depends(session_holder)]


def signed_in(user: SessionHolderDependency) -> SignedInUser:
    """The session's person once they have replaced a temporary password; until then only their
    session and the password change are open to them."""
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail={"reason": "password_change_required"}
        )
    return user


SignedInDependency = Annotated[SignedInUser, Depends(signed_in)]


def admin(user: SignedInDependency) -> SignedInUser:
    """The signed-in person where they are an admin; anyone else is refused."""
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admins only")
    return user


AdminDependency = Annotated[SignedInUser, Depends(admin)]
