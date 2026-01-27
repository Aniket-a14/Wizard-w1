import sys
from loguru import logger
from app.core.config import get_settings

settings = get_settings()

def configure_logger():
    logger.remove()  # Remove default handler
    
    # Stdout handler
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO"
    )
    
    # File rotation handler
    logger.add(
        "backend/logs/app.log",
        rotation="10 MB",
        retention="7 days",
        level="INFO"
    )

configure_logger()
