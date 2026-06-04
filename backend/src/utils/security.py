import bcrypt
import jwt
import uuid
from src.config import settings
from datetime import datetime, timedelta, timezone
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.session import get_db
from src.db.model import User
from sqlalchemy import select

SECRET_KEY = settings.JWT_SECRET_KEY
ALGORITHM = "HS256" # 签名算法
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # 过期时间

def create_access_token(user_id: str) -> str:
    """ 根据传入的 user_id 签发 JWT Access Token"""
    # 1. 计算过期时间(必须带有时区， 2026 年 Python 官方推荐使用 timezone.utc)
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    # 2. 准备 Payload 载荷 (sub 存 user_id， exp 存过期时间)
    to_encode = {"sub": user_id, "exp": expire}

    # 3. 使用秘钥核算进行签名加密，生成 Token 字符串
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_access_token(token: str) -> str | None:
    """ 解密并校验 Token, 如果合法则返回 user_id， 否则返回 None"""
    try:
        # 使用相同的秘钥解密 Token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        # 提取 sub 申明中的 user_id
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
        return user_id
    except jwt.InvalidTokenError:
        # 如果 Token 过期，被篡改或者格式错误，会触发 InvalidTokenError 异常，捕获并返回 None
        return None


def hash_password(password: str) -> str:
    """" 对明文密码进行 Bcrypt 单向加密 """
    # 1. 生成随机的盐(Salt)
    salt = bcrypt.gensalt()

    # 2. 对明文密码编码为 Bytes， 并混合 Salt 进行 Hash(bcrypt 底层是对字节流进行编码，所以要把 python 的字符串转换成字节码)
    hashed_bytes = bcrypt.hashpw(password.encode('utf-8'), salt)

    # 3. 将得到的字节码解码为普通的字符串，以便写入数据库
    return hashed_bytes.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """ 验证用户的输入的明文密码和数据库中的哈希值是否匹配 """
    # 1. 对明文密码进行编码
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')

    # 2. 调用 checkpw 安全校验(它会防止“时序攻击/Timeing Attack”）
    return bcrypt.checkpw(password_bytes, hashed_bytes)


# 申明 Bearer Token 拦截架构
# 在 Fastapi 路由中使用 Depends(security_schema) 时框架会自动拦截请求，并检查请求头
security_scheme = HTTPBearer()

async def get_current_user(
        credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
        db: AsyncSession = Depends(get_db)
) -> User:
    """
    鉴权依赖项（Fastapi Depends):
    1. 拦截并提取 Authorization 请求头中的 Token
    2. 解密校验 Token， 得到 user_id
    3. 穿透到数据库， 查验该用户是否真实存在，若存在则返回 User 实体对象，否则抛出异常
    """
    # 1.提取 Token 字符串
    token = credentials.credentials

    # 2. 校验并解密 Token 得到 user_id
    user_id_str = verify_access_token(token)
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录状态异常或已经过期，请重新登录",
            headers={"WWW-Authenticate": "Bearer"}
        )

    try:
        # 3. 解密出来的字符串换成 uuid 类型， 并在数据库中查询
        user_id = uuid.UUID(user_id_str)
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalars().first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户不存在或已经被禁用"
            )

        # 4. 鉴权成功， 将完整的用户对象注入到后方路由上下文中
        return user

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户凭证格式非法"
        )

