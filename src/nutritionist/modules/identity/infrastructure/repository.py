from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nutritionist.core.db import SqlAlchemyUnitOfWork
from nutritionist.core.ids import UserId
from nutritionist.modules.identity.domain.errors import EmailAlreadyRegisteredError
from nutritionist.modules.identity.domain.models import Email, User
from nutritionist.modules.identity.infrastructure.orm import UserRecord

_EMAIL_UNIQUE = "uq_users_email"


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UserId) -> User | None:
        record = await self._session.get(UserRecord, user_id)
        return _to_domain(record) if record else None

    async def get_by_email(self, email: Email) -> User | None:
        record = await self._session.scalar(
            select(UserRecord).where(UserRecord.email == email.value)
        )
        return _to_domain(record) if record else None

    def add(self, user: User) -> None:
        self._session.add(
            UserRecord(
                id=user.id,
                email=user.email.value,
                password_hash=user.password_hash,
                is_active=user.is_active,
                created_at=user.created_at,
            )
        )

    async def update(self, user: User) -> None:
        await self._session.execute(
            update(UserRecord)
            .where(UserRecord.id == user.id)
            .values(
                email=user.email.value,
                password_hash=user.password_hash,
                is_active=user.is_active,
            )
        )


class SqlAlchemyIdentityUnitOfWork(SqlAlchemyUnitOfWork):
    users: SqlAlchemyUserRepository

    def _bind_repositories(self, session: AsyncSession) -> None:
        self.users = SqlAlchemyUserRepository(session)

    async def commit(self) -> None:
        try:
            await super().commit()
        except IntegrityError as exc:
            # The race the use case's pre-check cannot close: two sign-ups at once.
            if _EMAIL_UNIQUE in str(exc.orig):
                raise EmailAlreadyRegisteredError() from exc
            raise


def _to_domain(record: UserRecord) -> User:
    return User(
        id=UserId(record.id),
        email=Email(record.email),
        password_hash=record.password_hash,
        created_at=record.created_at,
        is_active=record.is_active,
    )
