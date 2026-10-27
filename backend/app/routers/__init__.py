from app.routers.analyze import router as analyze_router
from app.routers.health import router as health_router
from app.routers.voice import router as voice_router
from app.routers.translate import router as translate_router

__all__ = ["analyze_router", "health_router", "voice_router", "translate_router"]
