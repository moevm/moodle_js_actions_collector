from fastapi import APIRouter, HTTPException, Body, Depends, Response
from fastapi.encoders import jsonable_encoder
from starlette import status

from src.core.modules.service.errors import UserNotFoundError, UserEmptyDataError
from src.depends import get_auth_service, get_access_tokens
from src.core.security import AccessTokens
from src.core.modules.service.authorization import AuthService
from src.models.user import AuthSession, SignInData

router = APIRouter()


@router.post(
    "/sign-in",
    status_code=status.HTTP_200_OK,
    response_description="User authorization",
    responses={401: {"description": "Invalid credentials"}, 503: {"description": "Authentication unavailable"}},
    response_model=AuthSession,
    response_model_by_alias=False,
)
async def signin(
    response: Response,
    user_raw_data: SignInData = Body(),
    service: AuthService = Depends(get_auth_service),
    tokens: AccessTokens = Depends(get_access_tokens),
):
    try:
        user_data = jsonable_encoder(user_raw_data)
        user = await service.sign_in(user_data["email"], user_data["password"])
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        response.headers["Cache-Control"] = "no-store"
        return {**user, "access_token": tokens.issue(user), "expires_in": tokens.settings.token_ttl_seconds}
    except HTTPException:
        raise
    except Exception as e:
        if isinstance(e, UserNotFoundError):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        elif isinstance(e, UserEmptyDataError):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        else:
            raise HTTPException(status_code=503, detail="Authentication is temporarily unavailable")
