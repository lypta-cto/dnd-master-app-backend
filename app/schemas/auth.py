from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserRead


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class AccessToken(BaseModel):
    """The refresh token is not in here on purpose — it goes out as an
    httpOnly cookie so no JavaScript on the page can read it."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class AuthResponse(AccessToken):
    user: UserRead


class MessageResponse(BaseModel):
    message: str
