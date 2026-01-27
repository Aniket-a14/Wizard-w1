from fastapi import APIRouter
from app.api.v1.endpoints import chat, data

api_router = APIRouter()

api_router.include_router(data.router, tags=["Data"])
api_router.include_router(chat.router, tags=["Chat"])
