"""Bodies of the people an admin manages."""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class AccountChangeRequest(BaseModel):
    """A new role, or whether the account is disabled; at least one."""

    role: Role | None = None
    disabled: bool | None = None

    @model_validator(mode="after")
    def names_a_change(self) -> Self:
        if self.role is None and self.disabled is None:
            raise ValueError("a change names a role or whether the account is disabled")
        return self


class IssuedPasswordResponse(BaseModel):
    """The account, and the temporary password just issued for it, shown this once."""

    model_config = ConfigDict(from_attributes=True)

    person: PersonResponse
    temporary_password: str


class PersonRefusedResponse(BaseModel):
    detail: str
