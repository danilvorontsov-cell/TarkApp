from fastapi import APIRouter
from app.config import settings
from app.services.gemini_service import gemini_tutor_service

router = APIRouter(tags=["Health"])


@router.get("/health")
@router.get("/api/v1/health")
async def health_check():
    has_live_client = gemini_tutor_service._client is not None
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
        "gemini_model": settings.GEMINI_MODEL,
        "mode": "live_gemini" if has_live_client else "pedagogical_mock",
    }
