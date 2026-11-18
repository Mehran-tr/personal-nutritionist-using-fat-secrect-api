from typing import Annotated

from fastapi import APIRouter, Depends, Request

from nutritionist.api.security import CurrentUserId
from nutritionist.modules.profile.api.schemas import ProfileIn, ProfileOut
from nutritionist.modules.profile.application.use_cases import ProfileUseCases

router = APIRouter(prefix="/me/profile", tags=["profile"])


def _profile(request: Request) -> ProfileUseCases:
    use_cases: ProfileUseCases = request.app.state.container.profile
    return use_cases


ProfileDep = Annotated[ProfileUseCases, Depends(_profile)]


@router.get("", response_model=ProfileOut, summary="Get my profile")
async def get_profile(user_id: CurrentUserId, use_cases: ProfileDep) -> ProfileOut:
    return ProfileOut.from_domain(await use_cases.get_profile.execute(user_id))


@router.put("", response_model=ProfileOut, summary="Create or replace my profile")
async def put_profile(user_id: CurrentUserId, body: ProfileIn, use_cases: ProfileDep) -> ProfileOut:
    profile = await use_cases.save_profile.execute(user_id, body.to_command())
    return ProfileOut.from_domain(profile)
