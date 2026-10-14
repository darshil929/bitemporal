"""Bodies of the first-run setup."""

from pydantic import BaseModel, Field


class SetupResponse(BaseModel):
    admin_exists: bool


class FirstAdminRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)


class SetupRefusedResponse(BaseModel):
    detail: str
