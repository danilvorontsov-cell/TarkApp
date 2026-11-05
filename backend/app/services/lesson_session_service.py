import time
import uuid
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from app.models.page_analysis import PageAnalysisResponse, UserProfile

logger = logging.getLogger("tarkapp.sessions")

# 10 minutes window for free spread appending as specified in requirements
SESSION_TIMEOUT_SECONDS = 600
MAX_PAGES_PER_SESSION = 2


@dataclass
class LessonSession:
    lesson_id: str
    device_id: str
    created_at: float
    expires_at: float
    profile: UserProfile
    images: List[Tuple[bytes, str]] = field(default_factory=list)
    page_count: int = 1
    analysis: Optional[PageAnalysisResponse] = None

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def seconds_remaining(self) -> int:
        return max(0, int(self.expires_at - time.time()))

    @property
    def can_append(self) -> bool:
        return (self.page_count < MAX_PAGES_PER_SESSION) and not self.is_expired


class LessonSessionService:
    def __init__(self):
        self._sessions: Dict[str, LessonSession] = {}

    def create_session(
        self,
        lesson_id: Optional[str] = None,
        device_id: str = "",
        profile: Optional[UserProfile] = None,
        images: Optional[List[Tuple[bytes, str]]] = None,
        analysis: Optional[PageAnalysisResponse] = None,
    ) -> LessonSession:
        """
        Creates and stores an active lesson session on initial page scan.
        Guarantees single balance point deduction per session lifecycle.
        """
        self.cleanup_expired_sessions()
        lid = lesson_id or f"ls_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        now = time.time()
        expires_at = now + SESSION_TIMEOUT_SECONDS
        img_list = list(images) if images else []

        session = LessonSession(
            lesson_id=lid,
            device_id=device_id or "",
            created_at=now,
            expires_at=expires_at,
            profile=profile or UserProfile(),
            images=img_list,
            page_count=len(img_list) if img_list else 1,
            analysis=analysis,
        )
        self._sessions[lid] = session
        logger.info(
            f"[SESSION] Created lesson session '{lid}' for device '{device_id}' "
            f"(pages={session.page_count}, ttl={SESSION_TIMEOUT_SECONDS}s)"
        )
        return session

    def get_session(self, lesson_id: str) -> Optional[LessonSession]:
        """Retrieves active lesson session by lesson_id."""
        return self._sessions.get(lesson_id)

    def append_image(
        self,
        lesson_id: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg"
    ) -> LessonSession:
        """
        Appends second page image to the active session.
        Enforces timeout (10 min) and maximum 2 pages quota limit.
        """
        session = self._sessions.get(lesson_id)
        if not session:
            raise KeyError(f"Session {lesson_id} not found")
        if session.is_expired:
            raise ValueError("SESSION_EXPIRED")
        if session.page_count >= MAX_PAGES_PER_SESSION:
            raise ValueError("PAGE_LIMIT_REACHED")

        session.images.append((image_bytes, mime_type))
        session.page_count = len(session.images)
        logger.info(
            f"[SESSION] Appended page to session '{lesson_id}'. "
            f"Total pages now: {session.page_count}/{MAX_PAGES_PER_SESSION}"
        )
        return session

    def update_analysis(
        self,
        lesson_id: str,
        analysis: PageAnalysisResponse
    ) -> Optional[LessonSession]:
        """Updates the comprehensive multimodal analysis of the session."""
        session = self._sessions.get(lesson_id)
        if session:
            session.analysis = analysis
        return session

    def cleanup_expired_sessions(self, max_idle_seconds: int = 900) -> int:
        """Prunes stale expired sessions (> 15 minutes) to conserve RAM."""
        now = time.time()
        expired_keys = [
            lid for lid, s in self._sessions.items()
            if now - s.created_at > max_idle_seconds
        ]
        for lid in expired_keys:
            del self._sessions[lid]
        return len(expired_keys)

    def clear(self):
        """Clears all sessions (for unit test environment isolation)."""
        self._sessions.clear()


lesson_session_service = LessonSessionService()
