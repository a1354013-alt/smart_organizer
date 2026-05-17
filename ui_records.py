from __future__ import annotations

import logging
import math

import streamlit as st

from report_exports import export_records_csv, export_records_markdown
from services import reclassify_record
from ui_common import (
    UIContext,
    format_timestamp_for_display,
    handle_ui_exception,
    safe_display_text,
)

logger = logging.getLogger(__name__)


def build_records_maintenance_actions(file_id_options: list[object]) -> list[dict[str, object]]:
    return [
        {"key": "refresh_locations", "label": "Refresh file locations", "requires_selection": False},
        {"key": "rebuild_fts", "label": "Rebuild FTS rows", "requires_selection": False},
        {
            "key": "do_reclassify",
            "label": "Reclassify selected record",
            "requires_selection": True,
            "enabled": bool(file_id_options),
        },
    ]


def render_records(context: UIContext) -> None:
    st.header("Organization Records")

    filter_values = context.storage.get_record_filter_values()
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        status = st.selectbox("Status", ["All", *filter_values.get("status", [])], index=0)
    with col2:
        topic = st.selectbox("Topic", ["All", *filter_values.get("main_topic", [])], index=0)
    with col3:
        file_type = st.selectbox("File type", ["All", *filter_values.get("file_type", [])], index=0)
    with col4:
        date_from = st.date_input("Created from", value=None)
    with col5:
        date_to = st.date_input("Created to", value=None)

    search = st.text_input("Search filename or summary", value="", placeholder="invoice / screenshot / contract")
    page_size = int(st.selectbox("Page size", [10, 25, 50, 100], index=1))
    current_page = max(1, int(st.number_input("Page", min_value=1, value=1, step=1)))

    page = context.storage.get_records_page(
        limit=page_size,
        offset=(current_page - 1) * page_size,
        status=None if status == "All" else status,
        main_topic=None if topic == "All" else topic,
        file_type=None if file_type == "All" else file_type,
        search=search or None,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
    )
    records = list(page.get("items") or [])
    display_records = [dict(record) for record in records]
    for record in display_records:
        record["created_at"] = format_timestamp_for_display(record.get("created_at"))
    total = int(page.get("total") or 0)
    file_id_options = [record.get("file_id") for record in records if record.get("file_id") is not None]

    page_count = max(1, math.ceil(total / page_size))
    if records:
        st.caption(f"Showing page {current_page} of {page_count} ({total} records)")
    else:
        st.info("No records match the current filters.")
        if search or status != "All" or topic != "All" or file_type != "All" or date_from or date_to:
            st.caption("Reset filters or clear search to bring records back into view.")

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
            st.download_button("Export current page as CSV", csv_payload, file_name="smart-organizer-records.csv", mime="text/csv")
        with export_col2:
            st.download_button("Export current page as Markdown", md_payload, file_name="smart-organizer-records.md", mime="text/markdown")

    st.subheader("Maintenance")
    maintenance_actions = build_records_maintenance_actions(file_id_options)
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button(str(maintenance_actions[0]["label"]), key=str(maintenance_actions[0]["key"])):
            try:
                with st.spinner("Refreshing file locations..."):
                    result = context.storage.refresh_file_locations(fix_moving=True)
                if result.get("success"):
                    st.success(safe_display_text(result.get("summary") or "Done"))
                else:
                    st.error(safe_display_text(result.get("error") or "Failed"))
            except Exception as exc:
                handle_ui_exception("Failed to refresh file locations.", exc)

    with col_b:
        if st.button(str(maintenance_actions[1]["label"]), key=str(maintenance_actions[1]["key"])):
            try:
                with st.spinner("Rebuilding FTS rows..."):
                    result = context.storage.reconcile_fts_rows()
                if result.get("success"):
                    st.success("FTS rows rebuilt successfully.")
                else:
                    st.error(safe_display_text(result.get("error") or "Failed"))
            except Exception as exc:
                handle_ui_exception("Failed to rebuild FTS rows.", exc)

    with col_c:
        st.caption("Use reclassify when a record needs a fresh metadata-based topic assignment.")

    if file_id_options:
        selected_file_id = st.selectbox("Reclassify file_id", file_id_options, index=0, key="reclassify_file_id")
        if st.button(str(maintenance_actions[2]["label"]), key=str(maintenance_actions[2]["key"])):
            try:
                with st.spinner("Reclassifying..."):
                    main_topic = reclassify_record(
                        storage=context.storage,
                        processor=context.processor,
                        file_id=int(selected_file_id),
                        processing_options=st.session_state.get("processing_options"),
                    )
                st.success(f"Updated topic: {safe_display_text(main_topic)}")
            except FileNotFoundError:
                st.error("The file is no longer available on disk. Refresh locations first.")
            except Exception as exc:
                logger.exception("reclassify_record failed")
                handle_ui_exception("Failed to reclassify record.", exc)
    else:
        st.caption("Reclassify becomes available after records are loaded. Refresh, rebuild, and reset remain available.")
