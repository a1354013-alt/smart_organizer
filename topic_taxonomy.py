from __future__ import annotations

from collections.abc import Mapping

CANONICAL_TOPIC_ALIASES: dict[str, str] = {
    "document.invoice": "document.invoice",
    "invoice": "document.invoice",
    "invoices": "document.invoice",
    "\u767c\u7968": "document.invoice",
    "document.contract": "document.contract",
    "contract": "document.contract",
    "contracts": "document.contract",
    "\u5408\u7d04": "document.contract",
    "document.quote": "document.quote",
    "quote": "document.quote",
    "quotes": "document.quote",
    "\u5831\u50f9\u55ae": "document.quote",
    "document.payment_request": "document.payment_request",
    "payment request": "document.payment_request",
    "\u4ed8\u6b3e\u7533\u8acb": "document.payment_request",
    "document.certificate": "document.certificate",
    "certificate": "document.certificate",
    "\u8b49\u660e\u6587\u4ef6": "document.certificate",
    "document.meeting_notes": "document.meeting_notes",
    "meeting notes": "document.meeting_notes",
    "\u6703\u8b70\u7d00\u9304": "document.meeting_notes",
    "document.scanned": "document.scanned",
    "scanned document": "document.scanned",
    "\u6383\u63cf\u6587\u4ef6": "document.scanned",
    "document.other": "document.other",
    "document": "document.other",
    "documents": "document.other",
    "docs": "document.other",
    "\u5176\u4ed6\u6587\u4ef6": "document.other",
    "\u6587\u4ef6": "document.other",
    "photo.people": "photo.people",
    "people": "photo.people",
    "\u4eba\u50cf": "photo.people",
    "photo.food": "photo.food",
    "food": "photo.food",
    "\u98df\u7269": "photo.food",
    "photo.travel": "photo.travel",
    "travel": "photo.travel",
    "\u65c5\u904a": "photo.travel",
    "photo.document_receipt": "photo.document_receipt",
    "document / receipt": "photo.document_receipt",
    "\u6587\u4ef6/\u6536\u64da": "photo.document_receipt",
    "photo.work": "photo.work",
    "work": "photo.work",
    "\u5de5\u4f5c": "photo.work",
    "photo.screenshot": "photo.screenshot",
    "screenshot": "photo.screenshot",
    "\u622a\u5716": "photo.screenshot",
    "photo.landscape": "photo.landscape",
    "landscape": "photo.landscape",
    "\u98a8\u666f": "photo.landscape",
    "photo.other": "photo.other",
    "photo": "photo.other",
    "photos": "photo.other",
    "\u5176\u4ed6\u5716\u7247": "photo.other",
    "\u5716\u7247": "photo.other",
    "video.unclassified": "video.unclassified",
    "unclassified": "video.unclassified",
    "\u672a\u5206\u985e\u5f71\u7247": "video.unclassified",
    "video.screen_recording": "video.screen_recording",
    "screen recording": "video.screen_recording",
    "\u87a2\u5e55\u9304\u5f71": "video.screen_recording",
    "video.tutorial": "video.tutorial",
    "tutorial": "video.tutorial",
    "\u6559\u5b78\u5f71\u7247": "video.tutorial",
    "video.meeting": "video.meeting",
    "meeting": "video.meeting",
    "\u6703\u8b70\u9304\u5f71": "video.meeting",
    "video.promo": "video.promo",
    "promo": "video.promo",
    "\u5ba3\u50b3\u5f71\u7247": "video.promo",
    "video.raw_footage": "video.raw_footage",
    "raw footage": "video.raw_footage",
    "\u539f\u59cb\u7d20\u6750": "video.raw_footage",
    "video.animation": "video.animation",
    "animation": "video.animation",
    "\u52d5\u756b": "video.animation",
    "video.other": "video.unclassified",
    "video": "video.unclassified",
    "videos": "video.unclassified",
    "\u5f71\u7247": "video.unclassified",
}

TOPIC_DISPLAY_LABELS: dict[str, dict[str, str]] = {
    "zh-TW": {
        "document.invoice": "\u767c\u7968",
        "document.contract": "\u5408\u7d04",
        "document.quote": "\u5831\u50f9\u55ae",
        "document.payment_request": "\u4ed8\u6b3e\u7533\u8acb",
        "document.certificate": "\u8b49\u660e\u6587\u4ef6",
        "document.meeting_notes": "\u6703\u8b70\u7d00\u9304",
        "document.scanned": "\u6383\u63cf\u6587\u4ef6",
        "document.other": "\u5176\u4ed6\u6587\u4ef6",
        "photo.people": "\u4eba\u50cf",
        "photo.food": "\u98df\u7269",
        "photo.travel": "\u65c5\u904a",
        "photo.document_receipt": "\u6587\u4ef6/\u6536\u64da",
        "photo.work": "\u5de5\u4f5c",
        "photo.screenshot": "\u622a\u5716",
        "photo.landscape": "\u98a8\u666f",
        "photo.other": "\u5176\u4ed6\u5716\u7247",
        "video.unclassified": "\u672a\u5206\u985e\u5f71\u7247",
        "video.screen_recording": "\u87a2\u5e55\u9304\u5f71",
        "video.tutorial": "\u6559\u5b78\u5f71\u7247",
        "video.meeting": "\u6703\u8b70\u9304\u5f71",
        "video.promo": "\u5ba3\u50b3\u5f71\u7247",
        "video.raw_footage": "\u539f\u59cb\u7d20\u6750",
        "video.animation": "\u52d5\u756b",
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


def normalize_topic_key(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return CANONICAL_TOPIC_ALIASES.get(raw.casefold(), CANONICAL_TOPIC_ALIASES.get(raw, raw))


def normalize_topic_scores(scores: Mapping[str, object] | None) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for raw_key, raw_score in (scores or {}).items():
        key = normalize_topic_key(raw_key)
        if not key:
            continue
        try:
            score = float(str(raw_score))
        except (TypeError, ValueError):
            score = 0.0
        normalized[key] = max(normalized.get(key, 0.0), score)
    return normalized


def topic_display_label(value: object, *, locale: str = "zh-TW") -> str:
    key = normalize_topic_key(value)
    locale_labels = TOPIC_DISPLAY_LABELS.get(locale, TOPIC_DISPLAY_LABELS["zh-TW"])
    return locale_labels.get(key, str(value or ""))
