"""Build a deterministic CCAC pipeline manifest from five local tool results."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .trusted import (
    ANALYTICAL_PRODUCERS,
    CONTRACT,
    REQUIRED_PRODUCERS,
    TrustedReportError,
    _producer,
    _timestamp,
    _validate_result,
)


def _time(value: str) -> str:
    return _timestamp(value, "manifest timestamp")


def build_manifest(
    paths: dict[str, Path], *, manifest_path: Path, started_at: str, completed_at: str
) -> dict[str, Any]:
    if set(paths) != set(ANALYTICAL_PRODUCERS):
        raise TrustedReportError("exactly five canonical producer paths are required")
    artifacts = []
    run_id = mode = None
    versions: dict[str, str] = {}
    documents: dict[str, dict[str, Any]] = {}
    base = manifest_path.resolve().parent
    for producer in ANALYTICAL_PRODUCERS:
        path = paths[producer].resolve()
        try:
            relative = Path(os.path.relpath(path, base))
            if ".." in relative.parts:
                raise TrustedReportError(
                    f"{producer} artifact must be inside the manifest directory"
                )
            raw = path.read_bytes()
            document = json.loads(raw)
        except FileNotFoundError as exc:
            raise TrustedReportError(f"artifact not found: {path}") from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TrustedReportError(
                f"unable to read {producer} artifact: {exc}"
            ) from exc
        if not isinstance(document, dict):
            raise TrustedReportError(
                f"{producer} path does not contain its canonical tool_result"
            )
        document_producer = _producer(document.get("producer"), f"{producer}.producer")
        if (
            document.get("contract") != CONTRACT
            or document.get("document_type") != "tool_result"
            or document_producer["name"] != producer
        ):
            raise TrustedReportError(
                f"{producer} path does not contain its canonical tool_result"
            )
        try:
            artifact_run = str(uuid.UUID(str(document.get("run_id"))))
        except (ValueError, TypeError) as exc:
            raise TrustedReportError(f"{producer} run_id is invalid") from exc
        if run_id is None:
            run_id = artifact_run
        elif run_id != artifact_run:
            raise TrustedReportError("producer run_ids do not match")
        artifact_mode = document.get("mode")
        if artifact_mode not in {"illustrative", "real"}:
            raise TrustedReportError(f"{producer} mode is invalid")
        if mode is None:
            mode = artifact_mode
        elif mode != artifact_mode:
            raise TrustedReportError("producer modes do not match")
        version = document_producer["version"]
        if not version:
            raise TrustedReportError(f"{producer} version is required")
        versions[producer] = version
        documents[producer] = document
        artifacts.append(
            {
                "producer": {"name": producer, "version": version},
                "document_type": "tool_result",
                "relative_path": relative.as_posix(),
                "content_sha256": hashlib.sha256(raw).hexdigest(),
                "status": "produced",
                "contract_valid": True,
                "omission_reason": None,
            }
        )
    assert run_id is not None and mode is not None
    for producer, document in documents.items():
        _validate_result(document, producer, run_id, mode)
    start = _time(started_at)
    completed = _time(completed_at)
    if datetime.fromisoformat(
        completed.replace("Z", "+00:00")
    ) < datetime.fromisoformat(start.replace("Z", "+00:00")):
        raise TrustedReportError("completed_at cannot be before started_at")
    return {
        "contract": CONTRACT,
        "document_type": "pipeline_manifest",
        "run_id": run_id,
        "mode": mode,
        "started_at": start,
        "completed_at": completed,
        "status": "complete",
        "required_producers": list(REQUIRED_PRODUCERS),
        "artifacts": artifacts,
        "errors": [],
    }
