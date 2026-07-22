from __future__ import annotations

import subprocess
from types import SimpleNamespace

from processors.llm_summary import generate_llm_summary, generate_llm_summary_result
from processors.pdf_processor import (
    extract_pdf_text,
    extract_pdf_text_with_timeout,
    generate_pdf_preview,
    ocr_pdf_sample,
)


class _FakeOpenAIClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content='{"summary": "整理完成", "tags": [" alpha ", "", "beta"]}'
                            )
                        )
                    ]
                )
            )
        )


class _BrokenOpenAIClient:
    def __init__(self) -> None:
        raise RuntimeError("boom")


def test_llm_summary_result_statuses_and_wrapper(monkeypatch):
    assert generate_llm_summary_result(
        "text",
        file_type="text",
        enabled=False,
        openai_client_class=_FakeOpenAIClient,
        model="model",
        timeout_seconds=5,
    ) == {"summary": None, "tags": [], "status": "disabled", "error": None}

    missing_sdk = generate_llm_summary_result(
        "text",
        file_type="text",
        enabled=True,
        openai_client_class=None,
        model="model",
        timeout_seconds=5,
    )
    assert missing_sdk["status"] == "failed"
    assert missing_sdk["summary"] is None

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    missing_key = generate_llm_summary_result(
        "text",
        file_type="text",
        enabled=True,
        openai_client_class=_FakeOpenAIClient,
        model="model",
        timeout_seconds=5,
    )
    assert missing_key["status"] == "disabled"

    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("LLM_TRUNCATE_CHARS", "4")
    ok = generate_llm_summary_result(
        "long text",
        file_type="text",
        enabled=True,
        openai_client_class=_FakeOpenAIClient,
        model="model",
        timeout_seconds=5,
    )
    assert ok["status"] == "ok"
    assert ok["tags"] == ["alpha", "beta"]
    assert "Input was truncated" in str(ok["summary"])

    summary, tags = generate_llm_summary(
        "text",
        file_type="text",
        enabled=True,
        openai_client_class=_FakeOpenAIClient,
        model="model",
        timeout_seconds=5,
    )
    assert summary is not None
    assert tags == ["alpha", "beta"]

    failed = generate_llm_summary_result(
        "text",
        file_type="text",
        enabled=True,
        openai_client_class=_BrokenOpenAIClient,
        model="model",
        timeout_seconds=5,
    )
    assert failed["status"] == "failed"
    assert "AI summary generation failed" in str(failed["error"])


def test_pdf_processor_helpers_cover_success_and_fallbacks(tmp_path):
    assert generate_pdf_preview("missing.pdf", convert_from_path_fn=None, poppler_path=None) is None

    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF")
    saved: list[tuple[str, str]] = []

    class FakeImage:
        def save(self, path: str, image_format: str) -> None:
            saved.append((path, image_format))

    preview = generate_pdf_preview(
        str(source),
        convert_from_path_fn=lambda *_args, **_kwargs: [FakeImage()],
        poppler_path=None,
        max_pages=2,
        timeout_seconds=3,
    )
    assert preview is not None
    assert saved == [(preview, "PNG")]

    class GoodPage:
        def extract_text(self) -> str:
            return "hello"

    class BadPage:
        def extract_text(self) -> str:
            raise RuntimeError("no text")

    class FakeReader:
        def __init__(self, _path: str) -> None:
            self.pages = [GoodPage(), BadPage(), GoodPage()]

    assert extract_pdf_text(str(source), pdf_reader=None) == ""
    assert extract_pdf_text(str(source), pdf_reader=FakeReader, max_pages=2) == "hello"
    assert extract_pdf_text_with_timeout(str(source), pdf_reader=None, max_pages=1, timeout_seconds=1) == (
        True,
        "",
        None,
    )
    assert extract_pdf_text_with_timeout(str(source), pdf_reader=FakeReader, max_pages=1, timeout_seconds=1) == (
        True,
        "hello",
        None,
    )

    def broken_reader(_path: str) -> object:
        raise ValueError("bad pdf")

    assert extract_pdf_text_with_timeout(str(source), pdf_reader=broken_reader, max_pages=1, timeout_seconds=1) == (
        True,
        "",
        None,
    )

    assert ocr_pdf_sample(
        str(source),
        convert_from_path_fn=None,
        pytesseract_module=object(),
        poppler_path=None,
    )[1].startswith("dependencies_missing")

    pytesseract = SimpleNamespace(image_to_string=lambda *_args, **_kwargs: "ocr text")
    assert ocr_pdf_sample(
        str(source),
        convert_from_path_fn=lambda *_args, **_kwargs: [object()],
        pytesseract_module=pytesseract,
        poppler_path=None,
        max_pages=1,
        timeout_seconds=1,
    ) == ("ocr text", None)

    pytesseract_timeout = SimpleNamespace(
        image_to_string=lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("t", 1))
    )
    assert ocr_pdf_sample(
        str(source),
        convert_from_path_fn=lambda *_args, **_kwargs: [object()],
        pytesseract_module=pytesseract_timeout,
        poppler_path=None,
        max_pages=1,
        timeout_seconds=1,
    ) == ("", None)

