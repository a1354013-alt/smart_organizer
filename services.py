"""
Services public API (facade).

`services.py` used to contain models + orchestration + persistence flows in one file.
It is now split into focused modules while keeping the import surface stable.
"""

from services_analysis import analyze_one_upload, analyze_upload_batch, analyze_upload_batch_async
from services_finalize import finalize_batch, finalize_one_file, persist_confirmed_metadata, reclassify_record
from services_models import (
    AnalysisResult,
    BatchAnalysisOutcome,
    DuplicateInfo,
    ExecutionResult,
    SummarySuggestion,
    UploadedFileData,
)
from services_review import apply_manual_topic_override, build_confirmed_results, generate_summary_suggestion

__all__ = [
    "UploadedFileData",
    "DuplicateInfo",
    "AnalysisResult",
    "ExecutionResult",
    "SummarySuggestion",
    "BatchAnalysisOutcome",
    "analyze_one_upload",
    "analyze_upload_batch",
    "analyze_upload_batch_async",
    "persist_confirmed_metadata",
    "apply_manual_topic_override",
    "build_confirmed_results",
    "generate_summary_suggestion",
    "finalize_one_file",
    "finalize_batch",
    "reclassify_record",
]

