from __future__ import annotations

import logging
import os
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from runtime_config import (
    LegacyDataMigrationError,
    RuntimeConfig,
    RuntimeDirectoryError,
    build_runtime_config,
    ensure_runtime_directories,
    migrate_legacy_data_if_needed,
)
from runtime_preflight import (
    SUPPORTED_PYTHON_RANGE,
    build_python_version_error,
    format_python_version,
    require_supported_python,
)

logger = logging.getLogger(__name__)


class StartupError(RuntimeError):
    def __init__(
        self,
        *,
        stage: str,
        summary: str,
        remediation: str,
        config: RuntimeConfig | None = None,
        legacy_detected: bool | None = None,
    ) -> None:
        super().__init__(summary)
        self.stage = stage
        self.summary = summary
        self.remediation = remediation
        self.config = config
        self.legacy_detected = legacy_detected
        self.reference_id = uuid.uuid4().hex[:12]


@dataclass(frozen=True, slots=True)
class StartupState:
    config: RuntimeConfig
    legacy_detected: bool


def _raise_startup_error(
    *,
    stage: str,
    summary: str,
    remediation: str,
    config: RuntimeConfig | None = None,
    legacy_detected: bool | None = None,
) -> NoReturn:
    raise StartupError(
        stage=stage,
        summary=summary,
        remediation=remediation,
        config=config,
        legacy_detected=legacy_detected,
    )


def _startup_error(
    *,
    stage: str,
    summary: str,
    remediation: str,
    config: RuntimeConfig | None = None,
    legacy_detected: bool | None = None,
) -> StartupError:
    return StartupError(
        stage=stage,
        summary=summary,
        remediation=remediation,
        config=config,
        legacy_detected=legacy_detected,
    )


def initialize_startup(project_root: Path | None = None) -> StartupState:
    try:
        require_supported_python()
    except RuntimeError:
        _raise_startup_error(
            stage="runtime preflight",
            summary=build_python_version_error(),
            remediation="Install Python 3.11 or 3.12 and restart Smart Organizer.",
        )

    try:
        config = build_runtime_config(project_root)
    except RuntimeDirectoryError as exc:
        raise _startup_error(
            stage="configuration resolution",
            summary="Runtime data directory could not be resolved.",
            remediation="Set SMART_ORGANIZER_DATA_DIR to a writable directory.",
        ) from exc

    try:
        legacy_status = migrate_legacy_data_if_needed(config)
    except LegacyDataMigrationError as exc:
        raise _startup_error(
            stage="legacy-data migration",
            summary=str(exc),
            remediation="Review the documented migration steps or choose an empty data directory.",
            config=config,
            legacy_detected=True,
        ) from exc

    try:
        ensure_runtime_directories(config)
    except RuntimeDirectoryError as exc:
        raise _startup_error(
            stage="runtime-directory validation",
            summary=str(exc),
            remediation="Choose a writable data directory with SMART_ORGANIZER_DATA_DIR.",
            config=config,
        ) from exc
    os.environ.setdefault("LOG_FILE", str(config.log_dir / "smart_organizer.log"))

    return StartupState(config=config, legacy_detected=legacy_status.has_legacy_data)


def render_startup_error(st_module: Any, error: StartupError) -> None:
    title = "Smart Organizer could not start safely"
    getattr(st_module, "set_page_config", lambda **kwargs: None)(page_title=title, layout="centered")
    st_module.error(title)
    st_module.markdown(f"**Stage:** {error.stage}")
    st_module.write(error.summary)
    st_module.markdown(f"**Detected Python:** `{format_python_version()}`")
    st_module.markdown(f"**Supported Python:** `{SUPPORTED_PYTHON_RANGE}`")
    if error.config is not None:
        st_module.markdown(f"**Runtime data directory:** `{error.config.data_root}`")
    if error.legacy_detected is not None:
        st_module.markdown(f"**Legacy data detected:** `{error.legacy_detected}`")
    st_module.info(error.remediation)
    st_module.code(error.reference_id)
    if st_module.button("Retry initialization"):
        st_module.rerun()


def run_with_startup_boundary(st_module: Any, run_app: Callable[[], None]) -> None:
    try:
        run_app()
    except StartupError as exc:
        logger.error("startup failed reference_id=%s stage=%s", exc.reference_id, exc.stage, exc_info=True)
        render_startup_error(st_module, exc)
    except Exception:
        reference_id = uuid.uuid4().hex[:12]
        logger.error("startup failed reference_id=%s", reference_id, exc_info=True)
        wrapped = StartupError(
            stage="application startup",
            summary="Application initialization failed before the normal UI could be rendered.",
            remediation="Check the application log and retry after fixing the reported configuration or database issue.",
        )
        wrapped.reference_id = reference_id
        logger.debug("raw startup traceback reference_id=%s\n%s", reference_id, traceback.format_exc())
        render_startup_error(st_module, wrapped)
