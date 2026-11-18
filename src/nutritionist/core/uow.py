"""Unit of Work port. Each module extends it with the repositories it needs."""

from types import TracebackType
from typing import Protocol, Self


class UnitOfWork(Protocol):
    """A transaction boundary owned by the use case, not by the HTTP request.

    Usage::

        async with self.uow() as uow:
            uow.users.add(user)
            await uow.commit()   # nothing is persisted without an explicit commit
    """

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...
