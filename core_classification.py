from __future__ import annotations

import os
from typing import Any

from core_utils import FileUtils


DOCUMENT_TAGS = ["發票", "合約", "報價", "請款", "證明文件", "會議紀錄", "掃描", "其他文件"]
PHOTO_TAGS = ["人物", "美食", "旅行", "文件/收據", "工作", "截圖", "風景", "其他照片"]
VIDEO_TAGS = ["Unclassified", "Screen Recording", "Tutorial", "Meeting", "Promo", "Raw Footage", "Animation"]

VIDEO_KEYWORD_RULES = {
    "Screen Recording": ["screen", "record", "screenshot", "desktop", "螢幕", "錄製", "畫面"],
    "Tutorial": ["tutorial", "howto", "how-to", "guide", "教學", "入門", "技巧", "lesson"],
    "Meeting": ["meeting", "conference", "zoom", "teams", "hangout", "會議", "簡報", "presentation"],
    "Promo": ["promo", "trailer", "teaser", "advertisement", "廣告", "宣傳", "預告"],
    "Raw Footage": ["raw", "footage", "clip", "rushes", "原始", "素材"],
    "Animation": ["animation", "animated", "cartoon", "anime", "動畫", "動漫"],
}


def classify_multi_tag(metadata: dict[str, Any], original_name: str, return_reason: bool = False):
    """多訊號加權分類（檔名 / 文字(OCR) / 掃描特徵 / 副檔名）。"""
    scores: dict[str, float] = {}
    reasons: list[str] = []
    original_name = original_name or ""
    name_lower = original_name.lower()
    text_lower = (metadata.get("extracted_text") or "").lower()
    ext = os.path.splitext(original_name)[1].lower()
    is_scanned = bool(metadata.get("is_scanned"))

    def add(tag, weight, why):
        scores[tag] = scores.get(tag, 0.0) + float(weight)
        reasons.append(f"{tag}: {why} (+{weight})")

    def sub(tag, weight, why):
        scores[tag] = scores.get(tag, 0.0) - float(weight)
        reasons.append(f"{tag}: {why} (-{weight})")

    is_document = metadata.get("file_type") == "document" or ext == ".pdf"
    is_video = metadata.get("file_type") == "video" or ext in FileUtils.VIDEO_EXTENSIONS

    if is_video:
        scores = {tag: 0.0 for tag in VIDEO_TAGS}
        matched = False
        video_tag_weights = {
            "Screen Recording": 0.85,
            "Tutorial": 0.9,
            "Meeting": 0.95,
            "Promo": 0.9,
            "Raw Footage": 0.8,
            "Animation": 0.9,
        }
        for tag, keywords in VIDEO_KEYWORD_RULES.items():
            for keyword in keywords:
                k = (keyword or "").lower()
                if not k:
                    continue
                if k in name_lower or k in text_lower:
                    add(tag, video_tag_weights.get(tag, 0.85), f"影片檔名/文字命中關鍵字: {keyword}")
                    matched = True
                    break

        if matched:
            add("Unclassified", 0.2, "影片分類 fallback（已命中規則）")
        else:
            scores["Unclassified"] = 1.0
            reasons.append("影片：未命中任何規則，預設為 Unclassified。")
        default_tag = "Unclassified"
    elif is_document:
        scores = {tag: 0.0 for tag in DOCUMENT_TAGS}
        rules = [
            (["統一編號", "發票", "收據", "invoice", "receipt"], "發票", 0.9),
            (["合約", "契約", "協議", "contract", "agreement"], "合約", 0.9),
            (["報價", "quotation", "estimate"], "報價", 0.8),
            (["請款", "付款", "payment"], "請款", 0.7),
            (["證明", "證書", "certificate"], "證明文件", 0.8),
            (["會議", "紀錄", "minutes", "meeting"], "會議紀錄", 0.8),
        ]

        for keywords, tag, w in rules:
            if any(k.lower() in name_lower for k in keywords):
                add(tag, w, f"檔名包含關鍵字 {keywords}")
            if any(k.lower() in text_lower for k in keywords):
                add(tag, w * 0.6, f"內容包含關鍵字 {keywords}")

        if is_scanned:
            add("掃描", 0.5, "偵測為掃描件（PDF 文字不足）")

        if ext in {".jpg", ".jpeg", ".png"}:
            for t in DOCUMENT_TAGS:
                sub(t, 0.2, "副檔名為圖片，降低文件類別信心")

        default_tag = "其他文件"
    else:
        scores = {tag: 0.0 for tag in PHOTO_TAGS}
        rules = [
            (["screenshot", "截圖", "螢幕截圖"], "截圖", 0.9),
            (["food", "美食", "餐"], "美食", 0.8),
            (["trip", "travel", "旅行", "旅遊"], "旅行", 0.8),
            (["receipt", "收據", "發票", "統一編號", "invoice"], "文件/收據", 0.9),
        ]

        for keywords, tag, w in rules:
            if any(k.lower() in name_lower for k in keywords):
                add(tag, w, f"檔名包含關鍵字 {keywords}")
            if any(k.lower() in text_lower for k in keywords):
                add(tag, w * 0.6, f"OCR/內容包含關鍵字 {keywords}")

        if ext == ".pdf":
            for t in PHOTO_TAGS:
                sub(t, 0.5, "副檔名為 PDF，降低照片類別信心")

        default_tag = "其他照片"

    results = {tag: min(max(score, 0.0), 1.0) for tag, score in scores.items() if score > 0.0}
    if not results:
        results[default_tag] = 1.0
        reasons.append(f"{default_tag}: 無明確規則命中，使用預設分類 (+1.0)")

    main_topic = max(results.keys(), key=lambda k: results[k])
    if return_reason:
        return main_topic, results, "\n".join(reasons[:30])
    return main_topic, results


def sync_manual_topic(main_topic: str, tag_scores: dict[str, float] | None, file_type: str):
    normalized_scores = dict(tag_scores or {})
    if not main_topic:
        return normalized_scores

    if file_type == "video":
        allowed_topics = VIDEO_TAGS
    elif file_type == "document":
        allowed_topics = DOCUMENT_TAGS
    else:
        allowed_topics = PHOTO_TAGS

    if main_topic not in allowed_topics:
        return normalized_scores

    if not normalized_scores:
        normalized_scores[main_topic] = 1.0
        return normalized_scores

    current_max = max(normalized_scores.values(), default=0.0)
    normalized_scores[main_topic] = max(normalized_scores.get(main_topic, 0.0), current_max, 1.0)
    return normalized_scores
