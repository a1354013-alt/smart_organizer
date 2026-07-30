from __future__ import annotations

from collections.abc import Mapping, Sequence

TOPICS_BY_FILE_TYPE: dict[str, tuple[str, ...]] = {
    "document": (
        "document.invoice",
        "document.contract",
        "document.quote",
        "document.payment_request",
        "document.certificate",
        "document.meeting_notes",
        "document.scanned",
        "document.other",
    ),
    "photo": (
        "photo.people",
        "photo.food",
        "photo.travel",
        "photo.document_receipt",
        "photo.work",
        "photo.screenshot",
        "photo.landscape",
        "photo.other",
    ),
    "video": (
        "video.unclassified",
        "video.screen_recording",
        "video.tutorial",
        "video.meeting",
        "video.promo",
        "video.raw_footage",
        "video.animation",
    ),
}

TOPIC_DISPLAY_LABELS: dict[str, dict[str, str]] = {
    "zh-TW": {
        "document.invoice": "發票",
        "document.contract": "合約",
        "document.quote": "報價單",
        "document.payment_request": "付款申請",
        "document.certificate": "證明文件",
        "document.meeting_notes": "會議紀錄",
        "document.scanned": "掃描文件",
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

LEGACY_TOPIC_ALIASES: dict[str, str] = {
    "invoice": "document.invoice",
    "invoices": "document.invoice",
    "發票": "document.invoice",
    "?潛巨": "document.invoice",
    "contract": "document.contract",
    "contracts": "document.contract",
    "agreement": "document.contract",
    "合約": "document.contract",
    "??": "document.contract",
    "quote": "document.quote",
    "quotes": "document.quote",
    "quotation": "document.quote",
    "estimate": "document.quote",
    "報價": "document.quote",
    "報價單": "document.quote",
    "?勗": "document.quote",
    "?勗??": "document.quote",
    "payment request": "document.payment_request",
    "payment": "document.payment_request",
    "請款": "document.payment_request",
    "付款申請": "document.payment_request",
    "隢狡": "document.payment_request",
    "隞狡": "document.payment_request",
    "隞狡?唾?": "document.payment_request",
    "certificate": "document.certificate",
    "證明文件": "document.certificate",
    "霅??辣": "document.certificate",
    "meeting notes": "document.meeting_notes",
    "minutes": "document.meeting_notes",
    "會議紀錄": "document.meeting_notes",
    "?降蝝??": "document.meeting_notes",
    "scanned document": "document.scanned",
    "掃描": "document.scanned",
    "掃描文件": "document.scanned",
    "??": "document.scanned",
    "???辣": "document.scanned",
    "document": "document.other",
    "documents": "document.other",
    "docs": "document.other",
    "其他文件": "document.other",
    "文件": "document.other",
    "?嗡??辣": "document.other",
    "?嗡???": "document.other",
    "people": "photo.people",
    "人物": "photo.people",
    "鈭箇": "photo.people",
    "food": "photo.food",
    "美食": "photo.food",
    "travel": "photo.travel",
    "trip": "photo.travel",
    "旅行": "photo.travel",
    "??": "photo.travel",
    "??": "photo.travel",
    "document / receipt": "photo.document_receipt",
    "receipt": "photo.document_receipt",
    "文件/收據": "photo.document_receipt",
    "憌": "photo.document_receipt",
    "?辣/?嗆?": "photo.document_receipt",
    "work": "photo.work",
    "工作": "photo.work",
    "鈭箏?": "photo.work",
    "screenshot": "photo.screenshot",
    "截圖": "photo.screenshot",
    "蝢?": "photo.food",
    "憸冽": "photo.screenshot",
    "?芸?": "photo.screenshot",
    "landscape": "photo.landscape",
    "風景": "photo.landscape",
    "撌乩?": "photo.landscape",
    "photo": "photo.other",
    "photos": "photo.other",
    "其他照片": "photo.other",
    "其他圖片": "photo.other",
    "圖片": "photo.other",
    "?嗡??抒?": "photo.other",
    "unclassified": "video.unclassified",
    "未分類影片": "video.unclassified",
    "video": "video.unclassified",
    "videos": "video.unclassified",
    "影片": "video.unclassified",
    "screen recording": "video.screen_recording",
    "螢幕錄影": "video.screen_recording",
    "tutorial": "video.tutorial",
    "教學影片": "video.tutorial",
    "meeting": "video.meeting",
    "會議錄影": "video.meeting",
    "promo": "video.promo",
    "宣傳影片": "video.promo",
    "raw footage": "video.raw_footage",
    "原始素材": "video.raw_footage",
    "animation": "video.animation",
    "動畫": "video.animation",
}

CANONICAL_TOPIC_ALIASES: dict[str, str] = {}
for topics in TOPICS_BY_FILE_TYPE.values():
    for topic in topics:
        CANONICAL_TOPIC_ALIASES[topic] = topic
        CANONICAL_TOPIC_ALIASES[topic.casefold()] = topic
for alias, topic in LEGACY_TOPIC_ALIASES.items():
    CANONICAL_TOPIC_ALIASES[alias] = topic
    CANONICAL_TOPIC_ALIASES[alias.casefold()] = topic


def canonical_topics_for_file_type(file_type: str) -> tuple[str, ...]:
    normalized = str(file_type or "").strip().lower()
    return TOPICS_BY_FILE_TYPE.get(normalized, TOPICS_BY_FILE_TYPE["document"])


def normalize_topic_key(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return CANONICAL_TOPIC_ALIASES.get(raw, CANONICAL_TOPIC_ALIASES.get(raw.casefold(), raw))


def normalize_topic_key_for_file_type(value: object, file_type: str) -> str:
    normalized = normalize_topic_key(value)
    return normalized if normalized in canonical_topics_for_file_type(file_type) else ""


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


def normalize_topic_scores_for_file_type(scores: Mapping[str, object] | None, file_type: str) -> dict[str, float]:
    allowed = set(canonical_topics_for_file_type(file_type))
    return {
        topic: score
        for topic, score in normalize_topic_scores(scores).items()
        if topic in allowed
    }


def topic_display_label(value: object, *, locale: str = "zh-TW") -> str:
    key = normalize_topic_key(value)
    locale_labels = TOPIC_DISPLAY_LABELS.get(locale, TOPIC_DISPLAY_LABELS["zh-TW"])
    return locale_labels.get(key, str(value or ""))


def is_canonical_topic(value: object, *, file_type: str | None = None) -> bool:
    key = normalize_topic_key(value)
    if not key:
        return False
    if file_type is None:
        return any(key in topics for topics in TOPICS_BY_FILE_TYPE.values())
    return key in canonical_topics_for_file_type(file_type)


def topic_file_type(value: object) -> str | None:
    key = normalize_topic_key(value)
    for file_type, topics in TOPICS_BY_FILE_TYPE.items():
        if key in topics:
            return file_type
    return None


def find_unknown_topics(values: Sequence[object], *, file_type: str | None = None) -> list[str]:
    unknown: list[str] = []
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        normalized = normalize_topic_key(raw)
        if not normalized:
            unknown.append(raw)
            continue
        if file_type is not None and normalized not in canonical_topics_for_file_type(file_type):
            unknown.append(raw)
    return unknown
