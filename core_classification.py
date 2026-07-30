from __future__ import annotations

import os
from typing import Any

from core_utils import FileUtils
from topic_taxonomy import (
    canonical_topics_for_file_type,
    normalize_topic_key,
    normalize_topic_scores_for_file_type,
)

DOCUMENT_TAGS = list(canonical_topics_for_file_type("document"))
PHOTO_TAGS = list(canonical_topics_for_file_type("photo"))
VIDEO_TAGS = list(canonical_topics_for_file_type("video"))

VIDEO_KEYWORD_RULES = {
    "video.screen_recording": ["screen", "record", "screenshot", "desktop"],
    "video.tutorial": ["tutorial", "howto", "how-to", "guide", "lesson"],
    "video.meeting": ["meeting", "conference", "zoom", "teams", "hangout", "presentation"],
    "video.promo": ["promo", "trailer", "teaser", "advertisement"],
    "video.raw_footage": ["raw", "footage", "clip", "rushes"],
    "video.animation": ["animation", "animated", "cartoon", "anime"],
}


def classify_multi_tag(metadata: dict[str, Any], original_name: str, return_reason: bool = False):
    scores: dict[str, float] = {}
    reasons: list[str] = []
    original_name = original_name or ""
    name_lower = original_name.lower()
    text_lower = str(metadata.get("extracted_text") or "").lower()
    ext = os.path.splitext(original_name)[1].lower()
    is_scanned = bool(metadata.get("is_scanned"))

    def add(tag: str, weight: float, why: str) -> None:
        scores[tag] = scores.get(tag, 0.0) + float(weight)
        reasons.append(f"{tag}: {why} (+{weight})")

    def sub(tag: str, weight: float, why: str) -> None:
        scores[tag] = scores.get(tag, 0.0) - float(weight)
        reasons.append(f"{tag}: {why} (-{weight})")

    is_document = metadata.get("file_type") == "document" or ext == ".pdf"
    is_video = metadata.get("file_type") == "video" or ext in FileUtils.VIDEO_EXTENSIONS

    if is_video:
        scores = dict.fromkeys(VIDEO_TAGS, 0.0)
        matched = False
        video_tag_weights = {
            "video.screen_recording": 0.85,
            "video.tutorial": 0.9,
            "video.meeting": 0.95,
            "video.promo": 0.9,
            "video.raw_footage": 0.8,
            "video.animation": 0.9,
        }
        for tag, keywords in VIDEO_KEYWORD_RULES.items():
            for keyword in keywords:
                k = keyword.lower()
                if k in name_lower or k in text_lower:
                    add(tag, video_tag_weights.get(tag, 0.85), f"matched keyword {keyword}")
                    matched = True
                    break
        default_tag = "video.unclassified"
        if matched:
            add(default_tag, 0.2, "fallback confidence retained")
        else:
            scores[default_tag] = 1.0
            reasons.append(f"{default_tag}: no video-specific signal found (+1.0)")
    elif is_document:
        scores = dict.fromkeys(DOCUMENT_TAGS, 0.0)
        rules = [
            (["invoice", "receipt", "發票"], "document.invoice", 0.9),
            (["contract", "agreement", "合約"], "document.contract", 0.9),
            (["quotation", "quote", "estimate", "報價"], "document.quote", 0.8),
            (["payment", "請款", "付款"], "document.payment_request", 0.7),
            (["certificate", "證明"], "document.certificate", 0.8),
            (["minutes", "meeting", "會議"], "document.meeting_notes", 0.8),
        ]
        for keywords, tag, weight in rules:
            if any(keyword.lower() in name_lower for keyword in keywords):
                add(tag, weight, f"matched filename keyword set {keywords}")
            if any(keyword.lower() in text_lower for keyword in keywords):
                add(tag, weight * 0.6, f"matched extracted-text keyword set {keywords}")
        if is_scanned:
            add("document.scanned", 0.5, "scanned document signal")
        if ext in {".jpg", ".jpeg", ".png"}:
            for tag in DOCUMENT_TAGS:
                sub(tag, 0.2, "image extension weakens document confidence")
        default_tag = "document.other"
    else:
        scores = dict.fromkeys(PHOTO_TAGS, 0.0)
        rules = [
            (["screenshot", "截圖"], "photo.screenshot", 0.9),
            (["food", "美食"], "photo.food", 0.8),
            (["trip", "travel", "旅行"], "photo.travel", 0.8),
            (["receipt", "invoice", "收據", "發票"], "photo.document_receipt", 0.9),
            (["people", "portrait", "人物"], "photo.people", 0.8),
            (["work", "office", "工作"], "photo.work", 0.7),
            (["landscape", "scenery", "風景"], "photo.landscape", 0.7),
        ]
        for keywords, tag, weight in rules:
            if any(keyword.lower() in name_lower for keyword in keywords):
                add(tag, weight, f"matched filename keyword set {keywords}")
            if any(keyword.lower() in text_lower for keyword in keywords):
                add(tag, weight * 0.6, f"matched extracted-text keyword set {keywords}")
        if ext == ".pdf":
            for tag in PHOTO_TAGS:
                sub(tag, 0.5, "pdf extension weakens photo confidence")
        default_tag = "photo.other"

    inferred_file_type = "video" if is_video else "document" if is_document else "photo"
    results = normalize_topic_scores_for_file_type(
        {tag: min(max(score, 0.0), 1.0) for tag, score in scores.items() if score > 0.0},
        inferred_file_type,
    )
    if not results:
        results[default_tag] = 1.0
        reasons.append(f"{default_tag}: fallback classification (+1.0)")

    main_topic = normalize_topic_key(max(results.keys(), key=lambda key: results[key]))
    if return_reason:
        return main_topic, results, "\n".join(reasons[:30])
    return main_topic, results


def sync_manual_topic(main_topic: str, tag_scores: dict[str, float] | None, file_type: str):
    normalized_topic = normalize_topic_key(main_topic)
    normalized_scores = normalize_topic_scores_for_file_type(tag_scores, file_type)
    allowed_topics = set(canonical_topics_for_file_type(file_type))
    if not normalized_topic or normalized_topic not in allowed_topics:
        return normalized_scores
    if not normalized_scores:
        normalized_scores[normalized_topic] = 1.0
        return normalized_scores
    current_max = max(normalized_scores.values(), default=0.0)
    normalized_scores[normalized_topic] = max(normalized_scores.get(normalized_topic, 0.0), current_max, 1.0)
    return normalized_scores
