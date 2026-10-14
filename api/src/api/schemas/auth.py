"""Bodies of signing in and its refusals."""

from datetime import datetime

from pydantic import BaseModel, Field

from api.services.sign_in import SignInRefusal


class SignInRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class SignInRefused(BaseModel):
    """Why a sign-in was refused, and until when where it is paused."""

    reason: SignInRefusal
    paused_until: datetime | None


class SignInRefusedResponse(BaseModel):
    detail: SignInRefused
