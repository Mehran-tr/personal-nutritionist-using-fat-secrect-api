from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from nutritionist.modules.identity.domain.models import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    AccessToken,
    User,
)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class LoginIn(BaseModel):
    # No format validation here: a malformed email must fail exactly like a wrong one.
    email: str = Field(max_length=320)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime

    @classmethod
    def from_domain(cls, token: AccessToken) -> "TokenOut":
        return cls(access_token=token.value, expires_at=token.expires_at)


class UserOut(BaseModel):
    id: UUID
    email: str
    created_at: datetime

    @classmethod
    def from_domain(cls, user: User) -> "UserOut":
        return cls(id=user.id, email=user.email.value, created_at=user.created_at)
