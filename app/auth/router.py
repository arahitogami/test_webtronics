from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from passlib.context import CryptContext

from sqlalchemy import select, exc, update
from sqlalchemy.ext.asyncio import AsyncSession

from .router_class import RouteAuth, RouteWithOutAuth
from .schemas import get_new_token
from .swagger_auth import *
from ..database import get_session
from . import schemas, models
from ..users.schemas import User, UserCreate, UserToken


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


router_auth = APIRouter(
    prefix="/auth",
    tags=["auth"],
    route_class=RouteAuth,
)

router_with_out_auth = APIRouter(
    prefix="/auth",
    tags=["auth"],
    route_class=RouteWithOutAuth,
)


@router_with_out_auth.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=User,
    responses=swagger_register,
)
async def register(
        form_data: UserCreate,
        session: Annotated[AsyncSession, Depends(get_session)],
):

    db_user = models.User(
        username=form_data.username,
        email=form_data.email,
        hashed_password=pwd_context.hash(form_data.password)
    )
    try:
        session.add(db_user)
        await session.commit()
    except exc.IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email has already been registered"
        )
    await session.refresh(db_user)
    return db_user


@router_with_out_auth.post(
    "/login",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.RespToken,
    responses=swagger_login,
)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    get_user = await session.scalars(
        select(models.User).where(
            models.User.email == form_data.username
        )
    )
    user: models.User = get_user.one_or_none()
    if not user or not pwd_context.verify(
            form_data.password, user.hashed_password
    ):
        raise HTTPException(
            status_code=404,
            detail="Invalid username or password",
        )

    token = schemas.create_token(
        user=UserToken.model_validate(user),
    )
    session.add(models.AuthToken(
        **token.model_dump(exclude=("token_type",))
    ))
    await session.commit()
    return token


@router_with_out_auth.post(
    "/token",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.RespToken,
    responses=swagger_create_token,
)
async def create_token(
    form_data: schemas.RefreshTokenBase,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """
    The valid refresh_token received during authorization
    allows to receive a new access_token. \n
    When a new access_token is obtained,
    the old access_token from the current authorization is no longer valid.
    """
    return await get_new_token(form_data.refresh_token, session=session)


@router_auth.delete(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def logout(
        request: Request,
        session: Annotated[AsyncSession, Depends(get_session)],
):
    result = await session.scalars(select(models.AuthToken).where(
        models.AuthToken.id == request.auth.id
    ))
    result = result.one_or_none()
    if result:
        result.is_active = False
        await session.commit()

    return


@router_auth.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    responses=swagger_change_password,
)
async def change_password(
        form_data: schemas.ChangePassword,
        request: Request,
        session: Annotated[AsyncSession, Depends(get_session)],
):
    """
    When you change the password, all other access_token and refresh_token
    from the authorization will be reset except for the current authorization.
    """
    if not pwd_context.verify(
        form_data.old_password, request.user.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The current password was entered incorrectly"
        )

    user = (await session.execute(select(models.User).where(
        models.User.id == request.user.id
    ))).scalars().one_or_none()
    user.hashed_password = pwd_context.hash(form_data.new_password)

    stmt = (
        update(models.AuthToken).
        where(models.AuthToken.id != request.auth.id,
              models.AuthToken.user_id == request.user.id).
        values(is_active=False)
    )
    await session.execute(stmt)

    await session.commit()

    return "Password changed successfully"
