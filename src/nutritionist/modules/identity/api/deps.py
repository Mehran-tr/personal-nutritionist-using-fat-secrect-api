from fastapi import Request

from nutritionist.modules.identity.application.use_cases import (
    AuthenticateUser,
    GetCurrentUser,
    IdentityUseCases,
    RegisterUser,
)

# Use cases are stateless and assembled once in bootstrap; requests share them.


def _identity(request: Request) -> IdentityUseCases:
    use_cases: IdentityUseCases = request.app.state.container.identity
    return use_cases


def register_user_use_case(request: Request) -> RegisterUser:
    return _identity(request).register_user


def authenticate_user_use_case(request: Request) -> AuthenticateUser:
    return _identity(request).authenticate_user


def get_current_user_use_case(request: Request) -> GetCurrentUser:
    return _identity(request).get_current_user
