import logging

from fastapi import APIRouter, HTTPException, Body, Depends, Response, Request
from fastapi.encoders import jsonable_encoder
from starlette import status

from src.core.modules.service.errors import UserNotFoundError, UserEmptyDataError
from src.depends import get_auth_service, get_access_tokens, get_login_limiter
from src.core.login_limits import LoginLimiter, LoginRateLimited
from src.core.security import AccessTokens
from src.core.modules.service.authorization import AuthService
from src.models.user import AuthSession, SignInData

router = APIRouter()
LOGGER = logging.getLogger(__name__)


@router.post(
    "/sign-in",
    status_code=status.HTTP_200_OK,
    response_description="User authorization",
    responses={401: {"description": "Invalid credentials"},
               429: {"description": "Login rate or concurrency limit; see Retry-After"},
               503: {"description": "Authentication unavailable"}},
    response_model=AuthSession,
    response_model_by_alias=False,
)
async def signin(
    request: Request,
    response: Response,
    user_raw_data: SignInData = Body(),
    service: AuthService = Depends(get_auth_service),
    tokens: AccessTokens = Depends(get_access_tokens),
    limiter: LoginLimiter = Depends(get_login_limiter),
):
    try:
        user_data = jsonable_encoder(user_raw_data)
        source = request.client.host if request.client is not None else "unknown"
        with limiter.check(source, user_data["email"]) as check:
            try:
                user = await service.sign_in(user_data["email"], user_data["password"])
            except (UserNotFoundError, UserEmptyDataError):
                check.failed = True
                raise HTTPException(401, "Invalid credentials", headers={"Cache-Control": "no-store"})
            if not user:
                check.failed = True
                raise HTTPException(401, "Invalid credentials", headers={"Cache-Control": "no-store"})
            response.headers["Cache-Control"] = "no-store"
            return {**user, "access_token": tokens.issue(user), "expires_in": tokens.settings.token_ttl_seconds}
    except LoginRateLimited as error:
        raise HTTPException(429, str(error), headers={
            "Retry-After": str(error.retry_after), "Cache-Control": "no-store",
        }) from error
    except HTTPException:
        raise
    except Exception as error:
        LOGGER.warning("Sign-in unavailable: %s", type(error).__name__)
        raise HTTPException(503, "Authentication is temporarily unavailable",
                            headers={"Cache-Control": "no-store"}) from error
