"""
Service module bridge re-exporting page analysis models, schema, and normalization functions.
Provides backward and cross-layer compatibility for app.services.page_analysis.
"""

from app.models.page_analysis import (
    AgeTier,
    AppendPageJsonRequest,
    AnalyzePageJsonRequest,
    GeminiPageAnalysisSchema,
    LessonSpeechLayer,
    PageAnalysisResponse,
    StepItem,
    SelfSolveStep,
    VocabularyItem,
    WorkedExample,
    is_full_audio_enabled,
    is_sentence_frame_enabled,
    normalize_est_tags,
    _enforce_est_tags,
    reconcile_worked_example_speech,
    sanitize_answer_template,
    strip_combining_accents,
)

__all__ = [
    "AgeTier",
    "AppendPageJsonRequest",
    "AnalyzePageJsonRequest",
    "GeminiPageAnalysisSchema",
    "LessonSpeechLayer",
    "PageAnalysisResponse",
    "StepItem",
    "SelfSolveStep",
    "VocabularyItem",
    "WorkedExample",
    "is_full_audio_enabled",
    "is_sentence_frame_enabled",
    "normalize_est_tags",
    "_enforce_est_tags",
    "reconcile_worked_example_speech",
    "sanitize_answer_template",
    "strip_combining_accents",
]
