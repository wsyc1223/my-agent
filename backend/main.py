from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from src.router.agent import router as agent_router
from src.router.conversation import router as conversation_router
from src.router.file_research import router as file_research_router
from src.router.auth import router as auth_router
from src.router.file import router as file_router
from fastapi.responses import JSONResponse
import traceback
from contextlib import asynccontextmanager
from src.graph import pool, checkpointer
import logging
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.open()
    await checkpointer.setup()
    yield

    await pool.close()

app = FastAPI(lifespan=lifespan)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code = 500,
        content = {
            "detail": str(exc),
            "error_code": 500,
        }
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agent_router)
app.include_router(conversation_router)
app.include_router(auth_router)
app.include_router(file_router)
app.include_router(file_research_router)
