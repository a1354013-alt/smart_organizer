from __future__ import annotations

import logging
import math

import streamlit as st

from i18n import t
from report_exports import export_records_csv, export_records_markdown
from services import (
    discard_unfinished_record,
    reanalyze_unfinished_record,
    reclassify_record,
    resume_unfinished_record,
)
from ui_common import (
    UIContext,
    format_timestamp_for_display,
    handle_ui_exception,
    safe_display_text,
)
from ui_labels import topic_display_label

logger = logging.getLogger(__name__)


def build_records_maintenance_actions(file_id_options: list[object]) -> list[dict[str, object]]:
    return [
        {"key": "refresh_locations", "label": t("search_records.maintenance_refresh"), "requires_selection": False},
        {"key": "rebuild_fts", "label": t("search_records.maintenance_rebuild_fts"), "requires_selection": False},
        {
            "key": "do_reclassify",
            "label": t("search_records.maintenance_reclassify"),
            "requires_selection": True,
            "enabled": bool(file_id_options),
        },
    ]


def build_unfinished_record_actions(record: dict[str, object]) -> list[str]:
    actions = record.get("available_actions")
    return [str(action) for action in actions] if isinstance(actions, list) else []


def _render_unfinished_records(context: UIContext) -> None:
    get_unfinished_records = getattr(context.storage, "get_unfinished_records", None)
    if get_unfinished_records is None:
        return
    st.subheader(t("search_records.unfinished_title"))
    records = get_unfinished_records(limit=50)
    if not records:
        st.caption(t("search_records.unfinished_empty"))
        return

    display_records: list[dict[str, object]] = []
    for record in records:
        display_records.append(
            {
                "file_id": record.get("file_id"),
                "original_name": record.get("original_name"),
                "status": record.get("status"),
                "created_at": format_timestamp_for_display(record.get("created_at")),
                "updated_at": format_timestamp_for_display(record.get("updated_at")),
                "temp_exists": t("common.yes") if record.get("temp_exists") else t("common.no"),
                "last_error": record.get("last_error") or "",
            }
        )
    st.dataframe(display_records, use_container_width=True)

    options = [int(record["file_id"]) for record in records if record.get("file_id") is not None]
    selected_file_id = st.selectbox(t("search_records.unfinished_select"), options, key="unfinished_file_id")
    selected = next((dict(record) for record in records if int(record.get("file_id") or -1) == int(selected_file_id)), {})
    actions = build_unfinished_record_actions(selected)
    if not actions:
        st.caption(t("search_records.unfinished_no_actions"))
        return

    cols = st.columns(3)
    if "resume" in actions:
        with cols[0]:
            if st.button(t("search_records.unfinished_resume"), key=f"unfinished_resume_{selected_file_id}"):
                try:
                    resumed = resume_unfinished_record(
                        storage=context.storage,
                        processor=context.processor,
                        file_id=int(selected_file_id),
                        processing_options=st.session_state.get("processing_options"),
                    )
                    st.session_state.analysis_results = [resumed]
                    st.success(t("search_records.unfinished_resume_success", name=safe_display_text(resumed.original_name)))
                except Exception as exc:
                    handle_ui_exception(t("search_records.unfinished_resume_failed"), exc)
    if "reanalyze" in actions:
        with cols[1]:
            if st.button(t("search_records.unfinished_reanalyze"), key=f"unfinished_reanalyze_{selected_file_id}"):
                try:
                    reanalyzed = reanalyze_unfinished_record(
                        storage=context.storage,
                        processor=context.processor,
                        file_id=int(selected_file_id),
                        processing_options=st.session_state.get("processing_options"),
                    )
                    st.session_state.analysis_results = [reanalyzed]
                    st.success(t("search_records.unfinished_reanalyze_success", name=safe_display_text(reanalyzed.original_name)))
                except Exception as exc:
                    handle_ui_exception(t("search_records.unfinished_reanalyze_failed"), exc)
    if "discard" in actions:
        with cols[2]:
            confirm = st.checkbox(
                t("search_records.unfinished_discard_confirm"),
                key=f"unfinished_discard_confirm_{selected_file_id}",
            )
            if st.button(
                t("search_records.unfinished_discard"),
                key=f"unfinished_discard_{selected_file_id}",
                disabled=not confirm,
            ):
                try:
                    discard_result = discard_unfinished_record(storage=context.storage, file_id=int(selected_file_id))
                    if discard_result.get("success"):
                        st.success(t("search_records.unfinished_discard_success"))
                    else:
                        cleanup_errors = discard_result.get("cleanup_errors")
                        cleanup_error_text = (
                            "; ".join(str(error) for error in cleanup_errors)
                            if isinstance(cleanup_errors, list)
                            else ""
                        )
                        st.warning(
                            t(
                                "search_records.unfinished_discard_partial",
                                errors=safe_display_text(cleanup_error_text),
                            )
                        )
                    st.rerun()
                except Exception as exc:
                    handle_ui_exception(t("search_records.unfinished_discard_failed"), exc)


def render_records(context: UIContext, *, show_header: bool = True) -> None:
    if show_header:
        st.header(t("search_records.records_title"))

    filter_values = context.storage.get_record_filter_values()
    display_topics = {value: topic_display_label(value) for value in filter_values.get("main_topic", [])}
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        status = st.selectbox(
            t("search_records.records_filters.status"),
            [t("search_records.records_filters.all"), *filter_values.get("status", [])],
            index=0,
        )
    with col2:
        topic = st.selectbox(
            t("search_records.records_filters.topic"),
            [t("search_records.records_filters.all"), *filter_values.get("main_topic", [])],
            index=0,
            format_func=lambda value: (
                t("search_records.records_filters.all")
                if value == t("search_records.records_filters.all")
                else display_topics.get(str(value), str(value))
            ),
        )
    with col3:
        file_type = st.selectbox(
            t("search_records.records_filters.file_type"),
            [t("search_records.records_filters.all"), *filter_values.get("file_type", [])],
            index=0,
        )
    with col4:
        date_from = st.date_input(t("search_records.records_filters.date_from"), value=None)
    with col5:
        date_to = st.date_input(t("search_records.records_filters.date_to"), value=None)

    search = st.text_input(
        t("search_records.records_filters.search"),
        value="",
        placeholder=t("search_records.search_input_placeholder"),
    )
    page_size = int(st.selectbox(t("search_records.records_filters.page_size"), [10, 25, 50, 100], index=1))
    current_page = max(1, int(st.number_input(t("search_records.records_filters.page"), min_value=1, value=1, step=1)))

    page = context.storage.get_records_page(
        limit=page_size,
        offset=(current_page - 1) * page_size,
        status=None if status == t("search_records.records_filters.all") else status,
        main_topic=None if topic == t("search_records.records_filters.all") else topic,
        file_type=None if file_type == t("search_records.records_filters.all") else file_type,
        search=search or None,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
    )
    records = list(page.get("items") or [])
    display_records = [dict(record) for record in records]
    for record in display_records:
        record["created_at"] = format_timestamp_for_display(record.get("created_at"))
        record["main_topic"] = topic_display_label(record.get("main_topic"))
        tags = [part.strip() for part in str(record.get("all_tags") or "").split(",") if part.strip()]
        if tags:
            record["all_tags"] = ", ".join(topic_display_label(tag) for tag in tags)
    total = int(page.get("total") or 0)
    file_id_options = [record.get("file_id") for record in records if record.get("file_id") is not None]

    page_count = max(1, math.ceil(total / page_size))
    if records:
        st.caption(t("search_records.records_showing_page", current_page=current_page, page_count=page_count, total=total))
    else:
        st.info(t("search_records.records_empty"))
        if (
            search
            or status != t("search_records.records_filters.all")
            or topic != t("search_records.records_filters.all")
            or file_type != t("search_records.records_filters.all")
            or date_from
            or date_to
        ):
            st.caption(t("search_records.records_reset_hint"))

    if records and context.pandas is not None:
        df = context.pandas.DataFrame(display_records)
        cols = [
            "file_id",
            "original_name",
            "file_type",
            "standard_date",
            "main_topic",
            "all_tags",
            "status",
            "manual_override",
            "last_error",
            "created_at",
        ]
        st.dataframe(df[[col for col in cols if col in df.columns]], use_container_width=True)
    elif records:
        st.dataframe(display_records, use_container_width=True)

    if records:
        csv_payload = export_records_csv(records)
        md_payload = export_records_markdown(records)
        export_col1, export_col2 = st.columns(2)
        with export_col1:
            st.download_button(
                t("search_records.records_export_csv"),
                csv_payload,
                file_name="smart-organizer-records.csv",
                mime="text/csv",
            )
        with export_col2:
            st.download_button(
                t("search_records.records_export_md"),
                md_payload,
                file_name="smart-organizer-records.md",
                mime="text/markdown",
            )

    st.subheader(t("search_records.maintenance_title"))
    maintenance_actions = build_records_maintenance_actions(file_id_options)
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button(str(maintenance_actions[0]["label"]), key=str(maintenance_actions[0]["key"])):
            try:
                with st.spinner(t("search_records.maintenance_refreshing")):
                    result = context.storage.refresh_file_locations(fix_moving=True)
                if result.get("success"):
                    st.success(safe_display_text(result.get("summary") or t("search_records.maintenance_done")))
                else:
                    st.error(safe_display_text(result.get("error") or t("search_records.maintenance_failed")))
            except Exception as exc:
                handle_ui_exception(t("search_records.refresh_failed"), exc)

    with col_b:
        if st.button(str(maintenance_actions[1]["label"]), key=str(maintenance_actions[1]["key"])):
            try:
                with st.spinner(t("search_records.maintenance_rebuilding")):
                    result = context.storage.reconcile_fts_rows()
                if result.get("success"):
                    st.success(t("search_records.maintenance_fts_success"))
                else:
                    st.error(safe_display_text(result.get("error") or t("search_records.maintenance_failed")))
            except Exception as exc:
                handle_ui_exception(t("search_records.rebuild_failed"), exc)

    with col_c:
        st.caption(t("search_records.maintenance_hint"))

    if file_id_options:
        selected_file_id = st.selectbox(
            t("search_records.reclassify_file_id"),
            file_id_options,
            index=0,
            key="reclassify_file_id",
        )
        if st.button(str(maintenance_actions[2]["label"]), key=str(maintenance_actions[2]["key"])):
            try:
                with st.spinner(t("search_records.maintenance_reclassifying")):
                    main_topic = reclassify_record(
                        storage=context.storage,
                        processor=context.processor,
                        file_id=int(selected_file_id),
                        processing_options=st.session_state.get("processing_options"),
                    )
                st.success(t("search_records.reclassify_success", topic=safe_display_text(main_topic)))
            except FileNotFoundError:
                st.error(t("search_records.reclassify_missing_file"))
            except Exception as exc:
                logger.exception("reclassify_record failed")
                handle_ui_exception(t("search_records.reclassify_failed"), exc)
    else:
        st.caption(t("search_records.reclassify_unavailable"))

    _render_unfinished_records(context)
