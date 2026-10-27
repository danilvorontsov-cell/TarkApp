import asyncio
import logging
from fastapi import APIRouter, status

from app.models.feedback import FeedbackCreate, FeedbackResponse
from app.services.telegram_alert import send_telegram_feedback

logger = logging.getLogger("tarkapp.feedback")

router = APIRouter(prefix="/api/v1", tags=["Feedback"])


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_200_OK,
    summary="Прием обратной связи и баг-репортов с телеметрией",
    description=(
        "Принимает баг-репорты и пожелания от пользователя, обогащает метаданными устройства "
        "и пересылает разработчику в Telegram с привязкой к Request ID."
    ),
)
async def submit_feedback(payload: FeedbackCreate) -> FeedbackResponse:
    # 1. Запись факта отправки фидбека в общий лог app.log
    logger.info(
        f"[FEEDBACK] category={payload.category} | contact={payload.contact} | "
        f"grade={payload.current_grade} | req_id={payload.last_request_id} | "
        f"device={payload.device_model} (OS: {payload.os_version}) | "
        f"msg={payload.message[:100]}..."
    )

    # 2. Неблокирующая отправка в Telegram администратору
    try:
        asyncio.create_task(send_telegram_feedback(payload.model_dump()))
    except Exception as e:
        logger.warning(f"Could not spawn Telegram task for feedback: {e}")

    # 3. Возврат успешного статуса клиенту
    return FeedbackResponse(
        success=True,
        message="Спасибо! Сообщение передано разработчику.",
    )
