from typing import Annotated

from fastapi import APIRouter, Depends, status, Request

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.router import reuseable_oauth
from app.auth.router_class import RouteAuth
from app.database import get_session
from app.users import models
from app.users.schemas import User


router_users = APIRouter(
    prefix="/user",
    tags=["Users"],
    route_class=RouteAuth,
    dependencies=[Depends(reuseable_oauth)]
)


@router_users.get(
    '/',
    status_code=status.HTTP_200_OK,
    response_model=User,
)
async def get_me(request: Request):
    return request.user


@router_users.delete(
    '/delete',
    status_code=status.HTTP_200_OK,
    response_model=User,
)
async def get_me(
        request: Request,
        session: Annotated[AsyncSession, Depends(get_session)],
):
    user = await session.get(
        models.User, request.user.id,
    )
    user.is_active = False
    await session.commit()
    return user
