from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, ConflictError
from app.db.session import get_db
from app.models.models import User
from app.repositories.user_repository import UserRepository
from app.schemas.schemas import (
    APIResponse,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
    UserWithTokenResponse,
)
from app.services.auth.auth_service import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserWithTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def register(
    payload: UserRegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserWithTokenResponse:
    repo = UserRepository(db)

    if await repo.get_by_email(payload.email):
        raise ConflictError("An account with this email already exists")
    if await repo.get_by_username(payload.username):
        raise ConflictError("Username is already taken")

    user = User(
        email=payload.email.lower(),
        username=payload.username,
        hashed_password=hash_password(payload.password),
        role="user",
    )
    user = await repo.create(user)

    access_token, expires_in = create_access_token(user.id, user.role)
    refresh_token, _ = create_refresh_token(user.id)

    return UserWithTokenResponse(
        message="Account created successfully",
        user=UserResponse.model_validate(user),
        tokens=TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        ),
    )


@router.post(
    "/login",
    response_model=UserWithTokenResponse,
    summary="Login and obtain JWT tokens",
)
async def login(
    payload: UserLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> UserWithTokenResponse:
    repo = UserRepository(db)
    user = await repo.get_by_email(payload.email.lower())

    if not user or not verify_password(payload.password, user.hashed_password):
        raise AuthenticationError("Invalid email or password")

    if not user.is_active:
        raise AuthenticationError("Account is disabled. Contact support.")

    access_token, expires_in = create_access_token(user.id, user.role)
    refresh_token, _ = create_refresh_token(user.id)

    return UserWithTokenResponse(
        message="Login successful",
        user=UserResponse.model_validate(user),
        tokens=TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        ),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current authenticated user",
)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.post(
    "/logout",
    response_model=APIResponse,
    summary="Logout (client should discard tokens)",
)
async def logout(current_user: User = Depends(get_current_user)) -> APIResponse:
    # Stateless JWT: client discards token
    # For full revocation, add token to a Redis blocklist here
    return APIResponse(message="Logged out successfully")
