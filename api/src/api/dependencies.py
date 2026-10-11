"""What an endpoint takes from the running application."""

from typing import Annotated, cast

from fastapi import Depends, Request

from api.db.database import Database


def database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


DatabaseDependency = Annotated[Database, Depends(database)]
