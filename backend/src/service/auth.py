from src.utils.security import create_access_token, verify_access_token, hash_password, verify_password
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.db.model import User, UserCredential

async def register_user(db: AsyncSession, email: str, password: str, name: str | None = None) -> dict:
    """
    用户注册服务逻辑
    """
    # 1. 查询邮箱是否被注册
    stmt = select(UserCredential).where(
        UserCredential.provider == "email",
        UserCredential.identifier == email
    )
    # 1.2 等待查询结果
    result = await db.execute(stmt)
    # 1.3 提取结果中的第一条记录（如果不存在则为None)
    existing_cred = result.scalars().first()
    # 1.3 判断是否存在，存在就抛出异常
    if existing_cred:
        raise Exception("该邮箱已经被注册")

    # 2. 不存在，则添加到用户表
    new_user =  User(name=name) if name else User()
    db.add(new_user)

    # 3. 冲刷事务获取分配的 UUID
    await db.flush()

    # 4. 对明文密码加密，并写入凭证表
    hashed = hash_password(password)
    new_cred = UserCredential(
        user_id=new_user.id,
        provider="email",
        identifier=email,
        password_hash=hashed
    )
    db.add(new_cred)

    # 5. 提交事务
    await db.commit()

    # 6. 签发 Token 并返回数据
    token = create_access_token(str(new_user.id))
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": new_user.id,
        "name": new_user.name
    }

async def login_user(db: AsyncSession, email: str, password: str):
    """
    用户登录服务逻辑
    """

    # 1、查询表中是否有该邮箱
    stmt = select(UserCredential).where(
        UserCredential.provider == "email",
        UserCredential.identifier == email
    )
    result = await db.execute(stmt)
    cred = result.scalars().first()

    # 如果邮箱不存在或者密码错误统一报错“邮箱或者密码错误”
    if not cred or not cred.password_hash:
        raise Exception("邮箱或者密码错误")

    # 2. 校验哈希码
    if not verify_password(password, cred.password_hash):
        raise Exception("邮箱或者密码错误")

    # 3. 查询关联的 User 表获得最新昵称
    user_stmt = select(User).where(User.id == cred.user_id)
    user_result = await db.execute(user_stmt)
    user = user_result.scalar_one()

    # 4. 签发 Token 并返回数据
    token = create_access_token(str(user.id))
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user.id,
        "name": user.name
    }
