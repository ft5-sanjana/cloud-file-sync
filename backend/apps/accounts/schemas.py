from __future__ import annotations

from datetime import datetime

from ninja import Schema
from pydantic import EmailStr, Field


class RegisterIn(Schema):
    name: str = Field(min_length=1, max_length=150)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(Schema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(Schema):
    id: int
    email: str
    name: str
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
    name: str


class ErrorOut(Schema):
    code: str
    message: str
