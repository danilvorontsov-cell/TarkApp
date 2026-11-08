import time
import uuid
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from app.models.page_analysis import PageAnalysisResponse, UserProfile

logger = logging.getLogger("tarkapp.sessions")

# 10 minutes window for free spread appending as specified in requirements
APPEND_WINDOW_SECONDS = 600
# Hard 15 minutes TTL for session in RAM before full eviction
SESSION_TTL_SECONDS = 900
SESSION_TIMEOUT_SECONDS = APPEND_WINDOW_SECONDS
MAX_PAGES_PER_SESSION = 2
MAX_ACTIVE_SESSIONS = 50


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
    last_accessed_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def seconds_remaining(self) -> int:
        return max(0, int(self.expires_at - time.time()))

    @property
    def can_append(self) -> bool:
        now = time.time()
        is_within_append_window = (now - self.created_at) <= APPEND_WINDOW_SECONDS
        return (self.page_count < MAX_PAGES_PER_SESSION) and not self.is_expired and is_within_append_window

    def free_image_buffers(self) -> None:
        """Explicitly drops binary image blobs to protect server RAM from OOM."""
        self.images.clear()


class LessonSessionService:
    def __init__(self, max_active_sessions: int = MAX_ACTIVE_SESSIONS, session_ttl: int = SESSION_TTL_SECONDS):
        self._sessions: Dict[str, LessonSession] = {}
        self.max_active_sessions = max_active_sessions
        self.session_ttl = session_ttl

    def cleanup_expired_sessions(self, max_idle_seconds: Optional[int] = None) -> int:
        """Prunes stale expired sessions (> 15 minutes) to conserve RAM."""
        now = time.time()
        ttl = max_idle_seconds or self.session_ttl
        expired_keys = [
            lid for lid, s in self._sessions.items()
            if (now - s.created_at > ttl)
        ]
        for lid in expired_keys:
            s = self._sessions.pop(lid, None)
            if s:
                s.free_image_buffers()
        return len(expired_keys)

    def _evict_if_needed(self) -> None:
        """Enforces MAX_ACTIVE_SESSIONS (50) by evicting oldest sessions (LRU/FIFO)."""
        self.cleanup_expired_sessions()
        while len(self._sessions) >= self.max_active_sessions:
            oldest_lid = min(self._sessions.keys(), key=lambda k: self._sessions[k].last_accessed_at)
            oldest = self._sessions.pop(oldest_lid)
            oldest.free_image_buffers()
            logger.info(f"[SESSION] Evicted session '{oldest_lid}' to enforce MAX_ACTIVE_SESSIONS ({self.max_active_sessions}) limit")

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
        Enforces MAX_ACTIVE_SESSIONS capacity limit with LRU eviction.
        """
        self._evict_if_needed()
        lid = lesson_id or f"ls_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        now = time.time()
        expires_at = now + self.session_ttl
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
            last_accessed_at=now,
        )
        self._sessions[lid] = session
        logger.info(
            f"[SESSION] Created lesson session '{lid}' for device '{device_id}' "
            f"(pages={session.page_count}, ttl={self.session_ttl}s, active_count={len(self._sessions)})"
        )
        return session

    def get_session(self, lesson_id: str) -> Optional[LessonSession]:
        """Retrieves active lesson session by lesson_id with automatic expiration pruning."""
        self.cleanup_expired_sessions()
        session = self._sessions.get(lesson_id)
        if not session:
            return None
        session.last_accessed_at = time.time()
        return session

    def append_image(
        self,
        lesson_id: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg"
    ) -> LessonSession:
        """
        Appends second page image to the active session.
        Enforces timeout (10 min append window) and maximum 2 pages quota limit.
        """
        session = self.get_session(lesson_id)
        if not session:
            raise KeyError(f"Session {lesson_id} not found")
        if not session.can_append:
            if session.page_count >= MAX_PAGES_PER_SESSION:
                raise ValueError("PAGE_LIMIT_REACHED")
            raise ValueError("SESSION_EXPIRED")

        session.images.append((image_bytes, mime_type))
        session.page_count = len(session.images)
        session.last_accessed_at = time.time()
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
        session = self.get_session(lesson_id)
        if session:
            session.analysis = analysis
            session.last_accessed_at = time.time()
        return session

    def clear(self):
        """Clears all sessions and frees image buffers (for test isolation)."""
        for s in self._sessions.values():
            s.free_image_buffers()
        self._sessions.clear()


lesson_session_service = LessonSessionService()
