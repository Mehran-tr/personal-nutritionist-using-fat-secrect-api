"""`CurrentUserId` dependency for any module's router.

Depends only on the core ``AccessTokenVerifier`` port, so feature modules never
import the identity module to protect their endpoints.
"""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from nutritionist.core.auth import AccessTokenVerifier
from nutritionist.core.exceptions import AuthenticationError
from nutritionist.core.ids import UserId

_bearer = HTTPBearer(auto_error=False, description="Access token from POST /auth/token")


def current_user_id(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> UserId:
    if credentials is None:
        raise AuthenticationError("Missing bearer token.")
    verifier: AccessTokenVerifier = request.app.state.container.token_verifier
    return verifier.verify(credentials.credentials)


CurrentUserId = Annotated[UserId, Depends(current_user_id)]
