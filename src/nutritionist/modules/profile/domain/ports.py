from typing import Protocol

from nutritionist.core.ids import UserId
from nutritionist.modules.profile.domain.models import Profile


class ProfileRepository(Protocol):
    async def get(self, user_id: UserId) -> Profile | None: ...

    async def save(self, profile: Profile) -> None:
        """Insert or replace the user's profile (one per user)."""
        ...
