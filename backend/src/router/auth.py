from fastapi import APIRouter, HTTPException, Depends, status
from src.schemas import RegisterRequest, LoginRequest, AuthResponse
from src.db.session import get_db
from sqlalchemy.ext.asyncio import AsyncSession 
from src.service.auth import register_user, login_user

router = APIRouter(tags=["Authentication"])

@router.post("/auth/register", response_model = AuthResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    try:
        result = await register_user(db, req.email, req.password, req.name)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.post("/auth/login", response_model = AuthResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    try:
        result = await login_user(db, req.email, req.password)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
