"""Bodies of the people an admin manages."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from api.services.sessions import Role


class PersonResponse(BaseModel):
    """An account: who holds it, their role, whether it is disabled or awaits a chosen password,
    when it was added and when its holder last signed in."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: Role
    disabled_at: datetime | None
    must_change_password: bool
    created_at: datetime
    last_signed_in: datetime | None


class NewPersonRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=80)
    role: Role


class AddedPersonResponse(BaseModel):
    """The account added, and the temporary password its holder signs in with, shown this once."""

    model_config = ConfigDict(from_attributes=True)

    person: PersonResponse
    temporary_password: str


class PersonRefusedResponse(BaseModel):
    detail: str
