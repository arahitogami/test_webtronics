import datetime

from fastapi import HTTPException, status
from jose import jwt, JWTError
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.auth import models
from app.users.schemas import UserToken

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_HOURS = settings.REFRESH_TOKEN_EXPIRE_HOURS


class ChangePassword(BaseModel):
    old_password: str
    new_password: str = Field(min_length=4, max_length=20)
    repeat_new_password: str = Field(min_length=4, max_length=20)

    @model_validator(mode="after")
    def check_passwords_match(self) -> "ChangePassword":
        o_p = self.old_password
        n_p = self.new_password
        r_n_p = self.repeat_new_password
        if n_p != r_n_p:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The new password does not match the repeated password"
            )
        if o_p == n_p:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The new password must not match the old password"
            )
        return self


class TokenBase(BaseModel):
    access_token: str
    token_type: str = Field(default="Bearer")


class RefreshTokenBase(BaseModel):

    refresh_token: str


class RespToken(TokenBase, RefreshTokenBase):
    pass


class Token(TokenBase, RefreshTokenBase):
    user_id: int


def create_token(
        user: UserToken,
        refresh_token: str = None
):
    if ACCESS_TOKEN_EXPIRE_MINUTES:
        expire = datetime.datetime.utcnow() + datetime.timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        )
    else:
        expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=15)

    if refresh_token:
        return Token(
            user_id=user.id,
            access_token=jwt.encode(
                {**user.model_dump(), "exp": expire},
                SECRET_KEY,
                algorithm=ALGORITHM
            ),
            refresh_token=refresh_token,
        )

    ref_expire = datetime.datetime.utcnow() + datetime.timedelta(
        hours=REFRESH_TOKEN_EXPIRE_HOURS
    )
    return Token(
        user_id=user.id,
        access_token=jwt.encode(
            {**user.model_dump(), "exp": expire},
            SECRET_KEY,
            algorithm=ALGORITHM
        ),
        refresh_token=jwt.encode(
            {**user.model_dump(), "exp": ref_expire},
            SECRET_KEY,
            algorithm=ALGORITHM
        ),
    )


async def get_new_token(
        refresh_token: str,
        session: AsyncSession,
):
    invalid_refresh_token = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise invalid_refresh_token

    match payload:
        case {
            "id": int() as user_id,
            "username": str() as username,
            "email": str() as email,
            "exp": int()
        }:
            user = await session.scalars(
                select(models.User).where(
                    models.User.id == user_id,
                    models.User.username == username,
                    models.User.email == email,
                    models.User.is_active == True,
                )
            )
            user = user.one_or_none()
            if not user:
                raise invalid_refresh_token

            auth = await session.scalars(
                select(models.AuthToken).where(
                    models.AuthToken.user_id == user.id,
                    models.AuthToken.refresh_token == refresh_token,
                    models.AuthToken.is_active == True,
                )
            )
            auth = auth.one_or_none()
            if not auth:
                raise invalid_refresh_token

            new_token: Token = create_token(
                user=UserToken.model_validate(user),
                refresh_token=refresh_token,
            )
            auth.access_token = new_token.access_token
            auth.last_update = datetime.datetime.now()
            await session.commit()
            return new_token
        case _:
            raise invalid_refresh_token
