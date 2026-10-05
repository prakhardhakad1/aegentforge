"""CSV upload route: POST /api/upload.

Contract (docs/INTERFACES.md): multipart field ``file``, ``.csv`` only, size
capped at ``MAX_UPLOAD_MB``; bytes are saved to
``{UPLOAD_DIR}/{dataset_id}.csv`` and parsed via ``connectors.parse_csv``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_api_key
from app.config import Settings, get_settings
from app.models import Dataset, new_uuid
from app.schemas.upload import UploadResponse

logger = logging.getLogger("agentforge.uploads")

router = APIRouter(
    tags=["Uploads"],
    dependencies=[Depends(require_api_key)],
)


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a CSV dataset",
    description=(
        "Multipart upload of a ``.csv`` file (max ``MAX_UPLOAD_MB``). The "
        "server profiles the file (row count, columns, dtypes, 20-row "
        "preview, quality notes), stores the bytes under the dataset id and "
        "returns the pinned upload response. Non-CSV -> 415, oversize -> 413, "
        "unparseable/empty -> 422."
    ),
)
async def upload_dataset(
    file: UploadFile = File(..., description="A .csv file"),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> UploadResponse:
    filename = file.filename or "upload.csv"
    if not filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Only .csv files are supported (got '{filename}')",
        )

    payload = await file.read()
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Uploaded CSV is empty",
        )
    if len(payload) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"File is {len(payload)} bytes; the cap is "
                f"{settings.max_upload_bytes} bytes (MAX_UPLOAD_MB="
                f"{settings.max_upload_mb})"
            ),
        )

    try:
        from connectors import parse_csv

        parsed = parse_csv(payload, filename=filename)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Could not parse CSV: {exc}",
        ) from exc
    except Exception as exc:  # noqa: BLE001 - connector failures are client errors
        logger.exception("CSV parsing failed for '%s'", filename)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Could not parse CSV: {type(exc).__name__}: {exc}",
        ) from exc

    dataset_id = new_uuid()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / f"{dataset_id}.csv"
    destination.write_bytes(payload)

    columns = [str(c) for c in (parsed.columns or [])]
    dtypes = {str(k): str(v) for k, v in (parsed.dtypes or {}).items()}
    preview = [[str(cell) for cell in row] for row in (parsed.preview or [])]
    quality_notes = [str(note) for note in (parsed.quality_notes or [])]

    row = Dataset(
        id=dataset_id,
        filename=getattr(parsed, "filename", None) or filename,
        original_name=filename,
        row_count=int(parsed.row_count or 0),
        columns_json=columns,
        dtypes_json=dtypes,
        preview_json=preview,
        quality_notes_json=quality_notes,
        path=str(destination),
        size_bytes=len(payload),
    )
    db.add(row)
    db.commit()

    logger.info(
        "Dataset %s stored (%d bytes, %d rows) at %s",
        dataset_id,
        len(payload),
        row.row_count,
        destination,
    )
    return UploadResponse(
        id=dataset_id,
        filename=row.filename,
        row_count=row.row_count,
        columns=columns,
        dtypes=dtypes,
        preview=preview,
        quality_notes=quality_notes,
    )
