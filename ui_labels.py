from __future__ import annotations

from collections.abc import Mapping

from folder_models import Recommendation
from i18n import t
from topic_taxonomy import topic_display_label

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


def recommendation_display_label(value: object) -> str:
    label_key = RECOMMENDATION_LABEL_KEYS.get(str(value))
    return t(label_key) if label_key else str(value)


def risk_display_label(value: object) -> str:
    label_key = RISK_LABEL_KEYS.get(str(value))
    return t(label_key) if label_key else str(value)


__all__ = [
    "recommendation_display_label",
    "risk_display_label",
    "topic_display_label",
]
