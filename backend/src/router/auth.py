from fastapi import APIRouter, HTTPException, Depends, status, Request
from src.schemas import RegisterRequest, LoginRequest, AuthResponse
from src.db.session import get_db
from sqlalchemy.ext.asyncio import AsyncSession 
from src.service.auth import register_user, login_user
from src.audit.logger import audit_log
from src.config import settings
from src.limiter import limiter

router = APIRouter(tags=["Authentication"])

@router.post("/auth/register", response_model = AuthResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def register(request: Request, req: RegisterRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    try:
        result = await register_user(db, req.email, req.password, req.name)
        await audit_log(
            action="register",
            resource="user",
            resource_id=str(result.user.id),
            user_id=result.user.id,
            success=True,
            detail={"identifier": req.email}
        )
        return result
    except Exception as e:
        await audit_log(
            action="register",
            resource="user",
            success=False,
            detail={"identifier": req.email, "error": str(e)}
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.post("/auth/login", response_model = AuthResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def login(request: Request, req: LoginRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    try:
        result = await login_user(db, req.email, req.password)
        await audit_log(
            action="login",
            resource="user",
            resource_id=str(result.user.id),
            user_id=result.user.id,
            success=True,
            detail={"identifier": req.email}
        )
        return result
    except Exception as e:
        await audit_log(
            action="login",
            resource="user",
            success=False,
            detail={"identifier": req.email, "error": str(e)}
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
