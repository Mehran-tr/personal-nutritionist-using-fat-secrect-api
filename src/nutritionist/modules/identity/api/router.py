from typing import Annotated

from fastapi import APIRouter, Depends, status

from nutritionist.api.security import CurrentUserId
from nutritionist.modules.identity.api.deps import (
    authenticate_user_use_case,
    get_current_user_use_case,
    register_user_use_case,
)
from nutritionist.modules.identity.api.schemas import LoginIn, RegisterIn, TokenOut, UserOut
from nutritionist.modules.identity.application.use_cases import (
    AuthenticateUser,
    GetCurrentUser,
    RegisterUser,
)

router = APIRouter(tags=["identity"])


@router.post(
    "/auth/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
)
async def register(
    body: RegisterIn,
    use_case: Annotated[RegisterUser, Depends(register_user_use_case)],
) -> UserOut:
    user = await use_case.execute(str(body.email), body.password)
    return UserOut.from_domain(user)


@router.post("/auth/token", response_model=TokenOut, summary="Exchange credentials for a token")
async def login(
    body: LoginIn,
    use_case: Annotated[AuthenticateUser, Depends(authenticate_user_use_case)],
) -> TokenOut:
    return TokenOut.from_domain(await use_case.execute(body.email, body.password))


@router.get("/me", response_model=UserOut, summary="The authenticated user")
async def me(
    user_id: CurrentUserId,
    use_case: Annotated[GetCurrentUser, Depends(get_current_user_use_case)],
) -> UserOut:
    return UserOut.from_domain(await use_case.execute(user_id))
