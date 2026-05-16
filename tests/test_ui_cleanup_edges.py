from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import ui_execute
import ui_renderers
import ui_review
import ui_search
from services import AnalysisResult, ExecutionResult
from storage import SearchContentError, StorageManager


class _ProgressRecorder:
    def __init__(self) -> None:
        self.values: list[float] = []

    def progress(self, value: float) -> None:
        self.values.append(value)


class _TextRecorder:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def text(self, value: str) -> None:
        self.messages.append(value)


def _noop(*args, **kwargs):  # noqa: ANN001, ANN002
    return None


class _SessionState(dict):
    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value):
        self[name] = value


def test_render_video_details_surfaces_ffprobe_and_thumbnail_warnings(monkeypatch):
    writes: list[str] = []
    warnings: list[str] = []

    fake_st = SimpleNamespace(
        write=lambda value: writes.append(str(value)),
        warning=lambda value: warnings.append(str(value)),
    )
    monkeypatch.setattr(ui_renderers, "st", fake_st)

    ui_renderers.render_video_details(
        {
            "video": {
                "duration_seconds": 62,
                "width": 320,
                "height": 240,
                "fps": 29.97,
                "video_codec": "h264",
                "file_size": 1024,
                "ffprobe_error": "ffprobe failed",
                "thumbnail_error": "thumbnail failed",
            }
        }
    )

    assert any("01:02" in message for message in writes)
    assert len(warnings) == 2


def test_render_execute_requires_confirmed_results(monkeypatch):
    messages: list[str] = []
    fake_st = SimpleNamespace(
        session_state={},
        header=_noop,
        info=lambda value: messages.append(str(value)),
    )
    monkeypatch.setattr(ui_execute, "st", fake_st)

    ui_execute.render_execute(SimpleNamespace(storage=None))

    assert any("Confirm reviewed items first" in message for message in messages)


def test_render_execute_resets_review_state_after_finalize(monkeypatch):
    progress = _ProgressRecorder()
    status = _TextRecorder()
    successes: list[str] = []
    errors: list[str] = []
    reset_calls: list[bool] = []
    session_state = _SessionState({
        "confirmed_results": ["placeholder"],
        "analysis_results": ["old-analysis"],
    })
    fake_st = SimpleNamespace(
        session_state=session_state,
        header=_noop,
        button=lambda *args, **kwargs: True,
        progress=lambda value=0: progress,
        empty=lambda: status,
        success=lambda value: successes.append(str(value)),
        error=lambda value: errors.append(str(value)),
    )
    monkeypatch.setattr(ui_execute, "st", fake_st)
    monkeypatch.setattr(
        ui_execute,
        "finalize_batch",
        lambda confirmed_results, storage, progress_callback: [
            progress_callback(1, 2, SimpleNamespace(original_name="a.pdf")),
            ExecutionResult(original_name="a.pdf", status="SUCCESS", new_path="/repo/a.pdf"),
            ExecutionResult(original_name="b.pdf", status="FAILED", error_message="disk full"),
        ][1:],
    )
    monkeypatch.setattr(ui_execute, "reset_review_state", lambda: reset_calls.append(True))

    ui_execute.render_execute(SimpleNamespace(storage=object()))

    assert progress.values[-1] == 1.0
    assert status.messages[-1] == "Organization completed."
    assert session_state["analysis_results"] == []
    assert session_state["confirmed_results"] == []
    assert session_state["execution_results"][0].status == "SUCCESS"
    assert reset_calls == [True]
    assert any("a.pdf -> /repo/a.pdf" in message for message in successes)
    assert any("b.pdf failed: disk full" in message for message in errors)


def test_render_search_handles_search_content_error(monkeypatch):
    errors: list[str] = []
    fake_st = SimpleNamespace(
        header=_noop,
        text_input=lambda *args, **kwargs: "invoice",
        spinner=lambda *args, **kwargs: nullcontext(),
        error=lambda value: errors.append(str(value)),
    )
    monkeypatch.setattr(ui_search, "st", fake_st)

    context = SimpleNamespace(storage=SimpleNamespace(search_content=lambda _query: (_ for _ in ()).throw(SearchContentError())))
    ui_search.render_search(context)

    assert errors


def test_render_review_rejects_non_list_analysis_results(monkeypatch):
    errors: list[str] = []
    fake_st = SimpleNamespace(
        session_state={"analysis_results": "bad-type"},
        header=_noop,
        info=_noop,
        error=lambda value: errors.append(str(value)),
        json=_noop,
    )
    monkeypatch.setattr(ui_review, "st", fake_st)
    monkeypatch.setattr(ui_review, "is_debug", lambda: False)

    ui_review.render_review(SimpleNamespace())

    assert errors


def test_render_review_shows_partial_warning_and_video_details(monkeypatch):
    warnings: list[str] = []
    video_calls: list[dict[str, object]] = []
    session_state = _SessionState({"analysis_results": [
        AnalysisResult(
            file_id=1,
            original_name="clip.mp4",
            file_type="video",
            standard_date="2026-01-01",
            main_topic="Travel",
            suggested_main_topic="Travel",
            tag_scores={"Travel": 1.0},
            classification_reason="rule",
            final_decision_reason="rule",
            metadata={"file_type": "video", "standard_date": "2026-01-01", "extracted_text": "", "is_scanned": False, "preview_path": None, "ocr_error": None, "notes": []},
            preview_path=None,
            is_scanned=False,
            analysis_status="PARTIAL",
            last_error="thumbnail skipped",
        )
    ], "review_summaries": {}, "ai_enabled": False})
    fake_st = SimpleNamespace(
        session_state=session_state,
        header=_noop,
        info=_noop,
        error=_noop,
        markdown=_noop,
        expander=lambda *args, **kwargs: nullcontext(),
        columns=lambda sizes: (nullcontext(), nullcontext()),
        subheader=_noop,
        image=_noop,
        warning=lambda value: warnings.append(str(value)),
        caption=_noop,
        json=_noop,
        write=_noop,
        selectbox=lambda label, options, index=0, key=None: options[index],
        button=lambda *args, **kwargs: False,
        code=_noop,
        success=_noop,
    )
    monkeypatch.setattr(ui_review, "st", fake_st)
    monkeypatch.setattr(ui_review, "render_video_details", lambda metadata: video_calls.append(dict(metadata)))
    monkeypatch.setattr(ui_review, "is_debug", lambda: False)

    ui_review.render_review(SimpleNamespace(storage=SimpleNamespace(path_exists=lambda path: False), processor=None))

    assert warnings
    assert video_calls


def test_refresh_file_locations_marks_missing_and_broken(tmp_path: Path):
    storage = StorageManager(str(tmp_path / "test.db"), str(tmp_path / "repo"), str(tmp_path / "uploads"))
    existing_temp = tmp_path / "uploads" / "temp.pdf"
    existing_temp.parent.mkdir(parents=True, exist_ok=True)
    existing_temp.write_bytes(b"%PDF-1.4\n%%EOF\n")

    conn = storage._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO files (original_name, safe_name, file_hash, file_type, status, final_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("done.pdf", "done.pdf", "hash-completed", "document", "COMPLETED", str(tmp_path / "repo" / "missing.pdf")),
        )
        cursor.execute(
            """
            INSERT INTO files (original_name, safe_name, file_hash, file_type, status, temp_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("pending.pdf", "pending.pdf", "hash-pending", "document", "PENDING", str(tmp_path / "uploads" / "missing-temp.pdf")),
        )
        cursor.execute(
            """
            INSERT INTO files (original_name, safe_name, file_hash, file_type, status, temp_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("ok.pdf", "ok.pdf", "hash-ok", "document", "PENDING", str(existing_temp)),
        )
        conn.commit()
    finally:
        conn.close()

    outcome = storage.refresh_file_locations()

    assert outcome["success"] is True
    assert outcome["summary"]["missing"] == 1
    assert outcome["summary"]["broken"] == 1
    assert storage.get_records_page(limit=10, offset=0)["total"] == 3

    statuses = {row["original_name"]: row["status"] for row in storage.get_records_page(limit=10, offset=0)["items"]}
    assert statuses["done.pdf"] == "MISSING"
    assert statuses["pending.pdf"] == "BROKEN"
    assert statuses["ok.pdf"] == "PENDING"
