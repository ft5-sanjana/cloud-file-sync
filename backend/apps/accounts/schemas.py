from __future__ import annotations

from datetime import datetime
from typing import Optional

from ninja import Schema
from pydantic import EmailStr, Field, model_validator


class RegisterIn(Schema):
    first_name: str = Field(min_length=1, max_length=75)
    last_name: str = Field(default="", max_length=75)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def _passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class LoginIn(Schema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(Schema):
    id: int
    email: str
    first_name: str
    last_name: str
    storage_quota: int
    storage_used: int
    date_joined: datetime


class TokenOut(Schema):
    access: str
    user: UserOut


class AccessOut(Schema):
    access: str


class RegisterOut(Schema):
    id: int
    email: str
    first_name: str
    last_name: str


class ProfileUpdateIn(Schema):
    # Both optional so the client can PATCH either field independently.
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=75)
    last_name: Optional[str] = Field(default=None, max_length=75)


class DeleteAccountIn(Schema):
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordIn(Schema):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
    confirm_new_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def _new_passwords_match(self):
        if self.new_password != self.confirm_new_password:
            raise ValueError("New passwords do not match.")
        return self


class ErrorOut(Schema):
    code: str
    message: str
