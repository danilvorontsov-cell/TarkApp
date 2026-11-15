import hmac
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status, Request, Header
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tts_audit import TTSAuditLog, TTSAuditLogItem, TTSAuditLogResponse
from app.limiter import safe_limit
from app.config import settings

logger = logging.getLogger("tarkapp.admin")

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


@router.get(
    "/tts-logs",
    response_model=TTSAuditLogResponse,
    summary="Административный просмотр истории и аудита запросов озвучки",
    description="Возвращает последние записи аудита синтеза речи (текст, SSML, ударения, эстонские теги, ошибки).",
)
@safe_limit("60/minute")
def get_tts_audit_logs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=1000, description="Количество последних записей"),
    only_errors: bool = Query(default=False, description="Фильтровать только ошибки синтеза"),
    x_admin_secret: Optional[str] = Header(None, alias="X-Admin-Secret"),
    db: Session = Depends(get_db),
) -> TTSAuditLogResponse:
    """
    Возвращает список последних записей аудита TTS из базы данных.
    Доступ защищен обязательной проверкой секретного заголовка X-Admin-Secret:
    curl -s -H "X-Admin-Secret: <SECRET>" https://api.tarkapp.ee/api/v1/admin/tts-logs?limit=5
    """
    expected_secret = (settings.ADMIN_SECRET or "").strip()
    provided_secret = (x_admin_secret or "").strip()
    if not expected_secret or not provided_secret or not hmac.compare_digest(provided_secret, expected_secret):
        logger.warning("[ADMIN] Unauthorized attempt to access /tts-logs - invalid or missing X-Admin-Secret")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ запрещен: неверный или отсутствующий ключ администратора",
        )

    try:
        query = db.query(TTSAuditLog)
        if only_errors:
            query = query.filter(
                (TTSAuditLog.status != "SUCCESS") | (TTSAuditLog.error_message.isnot(None))
            )
        total = query.count()
        items = query.order_by(TTSAuditLog.id.desc()).limit(limit).all()
        return TTSAuditLogResponse(
            items=[TTSAuditLogItem.model_validate(item) for item in items],
            total=total,
        )
    except Exception as e:
        logger.error(f"Failed to fetch TTS audit logs: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось получить логи аудита TTS.",
        )
