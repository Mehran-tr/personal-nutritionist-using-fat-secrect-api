"""The one auth contract every module may depend on.

Modules need to know *who* is calling, never *how* tokens work. The identity
module provides the implementation; the web layer wires it in.
"""

from typing import Protocol

from nutritionist.core.ids import UserId


class AccessTokenVerifier(Protocol):
    def verify(self, token: str) -> UserId:
        """Return the user id in a valid token, or raise ``AuthenticationError``."""
        ...
