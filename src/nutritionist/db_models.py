"""Imports every ORM module so ``Base.metadata`` is complete.

Used by Alembic (autogenerate/check) and by tests. Add new modules' ``orm`` here.
"""

from nutritionist.core.db import Base
from nutritionist.modules.identity.infrastructure import orm as identity_orm
from nutritionist.modules.profile.infrastructure import orm as profile_orm

__all__ = ["Base", "identity_orm", "profile_orm"]

metadata = Base.metadata
