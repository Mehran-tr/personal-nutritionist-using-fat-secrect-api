"""Identifiers shared across modules (the only cross-module domain vocabulary)."""

import uuid
from typing import NewType

UserId = NewType("UserId", uuid.UUID)


def new_user_id() -> UserId:
    return UserId(uuid.uuid4())
