from __future__ import annotations

from dataclasses import dataclass

from contracts import ExtractedMetadata


@dataclass(frozen=True, slots=True)
class UploadedFileData:
    name: str
    content: bytes
    mime_type: str = ""


@dataclass(frozen=True, slots=True)
class DuplicateInfo:
    filename: str
    status: str
    display: str
    final_path: str | None = None


@dataclass(slots=True)
class AnalysisResult:
    file_id: int
    original_name: str
    file_type: str
    standard_date: str
    main_topic: str
    suggested_main_topic: str
    tag_scores: dict[str, float]
    classification_reason: str
    final_decision_reason: str
    metadata: ExtractedMetadata
    preview_path: str | None
    is_scanned: bool
    summary: str | None = None
    manual_override: bool = False
    analysis_status: str = "OK"  # "OK" | "WARNING" | "PARTIAL"
    last_error: str | None = None
    step_timings: dict[str, float] | None = None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    original_name: str
    status: str  # "SUCCESS" | "FAILED"
    new_path: str | None = None
    file_id: int | None = None


@dataclass(frozen=True, slots=True)
class SummarySuggestion:
    summary: str
    llm_tags: list[str]


@dataclass(frozen=True, slots=True)
class BatchAnalysisOutcome:
    results: list[AnalysisResult]
    duplicates: list[DuplicateInfo]
    errors: list[str]

