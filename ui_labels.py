from __future__ import annotations

from collections.abc import Mapping

from folder_models import Recommendation

RECOMMENDATION_DISPLAY_LABELS_ZH_TW: Mapping[str, str] = {
    Recommendation.SAFE_TO_REVIEW.value: "\u53ef\u5b89\u5168\u8907\u67e5",
    Recommendation.NEEDS_MANUAL_CHECK.value: "\u9700\u8981\u4eba\u5de5\u78ba\u8a8d",
    Recommendation.DO_NOT_TOUCH.value: "\u4e0d\u8981\u64cd\u4f5c",
}


def recommendation_display_label(value: object) -> str:
    return RECOMMENDATION_DISPLAY_LABELS_ZH_TW.get(str(value), str(value))
