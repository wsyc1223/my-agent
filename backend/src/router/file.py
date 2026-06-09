from fastapi import APIRouter, Depends, UploadFile, BackgroundTasks, HTTPException, File
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.session import get_db
from src.utils.security import get_current_user
from src.db.model import User
from src.service.file_research import handle_file_upload

router = APIRouter(prefix="/file", tags=["file"])

@router.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        # 1. 从 fastapi 接收的文件对象中读取二进制字节流
        file_data = await file.read()

        # 2. 转换成为字符串
        res = await handle_file_upload(
            user_id=str(user.id), 
            filename=file.filename, 
            file_data=file_data, 
            db=db, 
            background_tasks=background_tasks)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
