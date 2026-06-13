from __future__ import annotations

from collections.abc import Mapping

from folder_models import Recommendation
from i18n import t

RECOMMENDATION_LABEL_KEYS: Mapping[str, str] = {
    Recommendation.SAFE_TO_REVIEW.value: "labels.recommendation.safe_to_review",
    Recommendation.NEEDS_MANUAL_CHECK.value: "labels.recommendation.needs_manual_check",
    Recommendation.DO_NOT_TOUCH.value: "labels.recommendation.do_not_touch",
}

RISK_LABEL_KEYS: Mapping[str, str] = {
    Recommendation.SAFE_TO_REVIEW.value: "labels.risk.safe_to_review",
    Recommendation.NEEDS_MANUAL_CHECK.value: "labels.risk.needs_manual_check",
    Recommendation.DO_NOT_TOUCH.value: "labels.risk.do_not_touch",
}

TOPIC_KEY_ALIASES: Mapping[str, str] = {
    "發票": "document.invoice",
    "合約": "document.contract",
    "報價": "document.quote",
    "請款": "document.payment_request",
    "證明文件": "document.certificate",
    "會議紀錄": "document.meeting_notes",
    "掃描": "document.scanned",
    "其他文件": "document.other",
    "人物": "photo.people",
    "美食": "photo.food",
    "旅行": "photo.travel",
    "文件/收據": "photo.document_receipt",
    "工作": "photo.work",
    "截圖": "photo.screenshot",
    "風景": "photo.landscape",
    "其他照片": "photo.other",
    "Unclassified": "video.unclassified",
    "Screen Recording": "video.screen_recording",
    "Tutorial": "video.tutorial",
    "Meeting": "video.meeting",
    "Promo": "video.promo",
    "Raw Footage": "video.raw_footage",
    "Animation": "video.animation",
}

TOPIC_DISPLAY_LABELS: Mapping[str, Mapping[str, str]] = {
    "zh-TW": {
        "document.invoice": "發票",
        "document.contract": "合約",
        "document.quote": "報價",
        "document.payment_request": "請款",
        "document.certificate": "證明文件",
        "document.meeting_notes": "會議紀錄",
        "document.scanned": "掃描",
        "document.other": "其他文件",
        "photo.people": "人物",
        "photo.food": "美食",
        "photo.travel": "旅行",
        "photo.document_receipt": "文件/收據",
        "photo.work": "工作",
        "photo.screenshot": "截圖",
        "photo.landscape": "風景",
        "photo.other": "其他照片",
        "video.unclassified": "未分類影片",
        "video.screen_recording": "螢幕錄影",
        "video.tutorial": "教學影片",
        "video.meeting": "會議錄影",
        "video.promo": "宣傳影片",
        "video.raw_footage": "原始素材",
        "video.animation": "動畫",
    },
    "en": {
        "document.invoice": "Invoice",
        "document.contract": "Contract",
        "document.quote": "Quote",
        "document.payment_request": "Payment Request",
        "document.certificate": "Certificate",
        "document.meeting_notes": "Meeting Notes",
        "document.scanned": "Scanned Document",
        "document.other": "Other Document",
        "photo.people": "People",
        "photo.food": "Food",
        "photo.travel": "Travel",
        "photo.document_receipt": "Document / Receipt",
        "photo.work": "Work",
        "photo.screenshot": "Screenshot",
        "photo.landscape": "Landscape",
        "photo.other": "Other Photo",
        "video.unclassified": "Unclassified",
        "video.screen_recording": "Screen Recording",
        "video.tutorial": "Tutorial",
        "video.meeting": "Meeting",
        "video.promo": "Promo",
        "video.raw_footage": "Raw Footage",
        "video.animation": "Animation",
    },
}


def recommendation_display_label(value: object) -> str:
    label_key = RECOMMENDATION_LABEL_KEYS.get(str(value))
    return t(label_key) if label_key else str(value)


def risk_display_label(value: object) -> str:
    label_key = RISK_LABEL_KEYS.get(str(value))
    return t(label_key) if label_key else str(value)


def topic_display_label(value: object, *, locale: str = "zh-TW") -> str:
    raw = str(value or "")
    canonical = TOPIC_KEY_ALIASES.get(raw, raw)
    locale_labels = TOPIC_DISPLAY_LABELS.get(locale, TOPIC_DISPLAY_LABELS["zh-TW"])
    return locale_labels.get(canonical, raw)
