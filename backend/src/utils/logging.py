import structlog
import logging
import sys


import time
from functools import wraps

def configure_logger():
    # ... (existing config) ...
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.ConsoleRenderer() if sys.stdout.isatty() else structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

logger = structlog.get_logger()

def trace_agent(agent_name: str):
    """Decorator to trace agent execution time and outcomes."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            logger.info(f"Agent Started: {agent_name}", status="started")
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                logger.info(f"Agent Finished: {agent_name}", 
                            status="success", 
                            duration_sec=round(duration, 3))
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"Agent Failed: {agent_name}", 
                             status="error", 
                             error=str(e),
                             duration_sec=round(duration, 3))
                raise
        return wrapper
    return decorator
