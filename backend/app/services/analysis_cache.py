import hashlib
import logging
from collections import OrderedDict
from typing import List, Optional
from app.models.page_analysis import PageAnalysisResponse, UserProfile

logger = logging.getLogger("tarkapp.cache")

# In-memory LRU cache for lesson analysis responses: cache_key -> PageAnalysisResponse
_ANALYSIS_CACHE: OrderedDict[str, PageAnalysisResponse] = OrderedDict()
MAX_ANALYSIS_CACHE_ENTRIES: int = 500


def compute_analysis_cache_key(
    images_bytes: List[bytes],
    profile: Optional[UserProfile] = None,
) -> str:
    """
    Computes a deterministic cryptographic fingerprint hash for an analysis request
    based on the exact content of all pages and the student's pedagogical profile.
    """
    hasher = hashlib.sha256()

    # Hash page images in order
    for img in images_bytes:
        hasher.update(hashlib.sha256(img).digest())

    # Hash profile parameters safely (grade, tier, sorted interests)
    grade_val = str(getattr(profile, "grade", "") or "")
    tier_obj = getattr(profile, "tier", None)
    tier_val = str(getattr(tier_obj, "value", tier_obj or ""))

    interests_list: List[str] = []
    profile_interests = getattr(profile, "interests", None)
    if profile_interests:
        for it in profile_interests:
            val = getattr(it, "value", str(it))
            interests_list.append(str(val))
    interests_str = ",".join(sorted(interests_list))

    meta_payload = f"grade:{grade_val}|tier:{tier_val}|interests:{interests_str}"
    hasher.update(meta_payload.encode("utf-8"))

    return hasher.hexdigest()


def get_cached_analysis(cache_key: str) -> Optional[PageAnalysisResponse]:
    """Retrieves cached PageAnalysisResponse if present and marks it recently used (LRU)."""
    if cache_key in _ANALYSIS_CACHE:
        _ANALYSIS_CACHE.move_to_end(cache_key)
        logger.info(f"[CACHE] Lesson analysis cache HIT for key={cache_key[:12]}")
        return _ANALYSIS_CACHE[cache_key]
    return None


def store_cached_analysis(cache_key: str, data: PageAnalysisResponse) -> None:
    """Stores PageAnalysisResponse in the LRU cache with automatic FIFO eviction."""
    if len(_ANALYSIS_CACHE) >= MAX_ANALYSIS_CACHE_ENTRIES:
        # Evict oldest 20% entries
        evict_count = max(1, MAX_ANALYSIS_CACHE_ENTRIES // 5)
        for _ in range(evict_count):
            try:
                _ANALYSIS_CACHE.popitem(last=False)
            except KeyError:
                break

    _ANALYSIS_CACHE[cache_key] = data
    _ANALYSIS_CACHE.move_to_end(cache_key)
    logger.info(
        f"[CACHE] Saved lesson analysis to cache for key={cache_key[:12]} "
        f"(total entries: {len(_ANALYSIS_CACHE)}/{MAX_ANALYSIS_CACHE_ENTRIES})"
    )


def clear_analysis_cache() -> None:
    """Clears analysis cache (used in maintenance and tests)."""
    _ANALYSIS_CACHE.clear()
