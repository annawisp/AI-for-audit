import hashlib
import re
from pathlib import Path

from fastapi import UploadFile

from app.core.config import Settings
from app.services.repository import new_document_id

SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


class UploadValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def resolve_upload_dir(settings: Settings) -> Path:
    path = Path(settings.upload_dir)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[3] / path
    return path.resolve()


def sanitize_filename(filename: str) -> str:
    original_name = Path(filename).name
    sanitized = SAFE_FILENAME_PATTERN.sub("_", original_name).strip("._")
    return sanitized or "uploaded_file"


def validate_filename(filename: str, settings: Settings) -> str:
    sanitized = sanitize_filename(filename)
    suffix = Path(sanitized).suffix.lower()
    if suffix not in settings.allowed_upload_extensions:
        allowed = ", ".join(sorted(settings.allowed_upload_extensions))
        raise UploadValidationError(
            "unsupported_file_type",
            f"Unsupported file type. Allowed extensions: {allowed}",
        )
    return sanitized


async def save_upload_file(
    *,
    project_id: str,
    upload_file: UploadFile,
    settings: Settings,
) -> dict[str, str | int]:
    original_filename = upload_file.filename or ""
    safe_filename = validate_filename(original_filename, settings)
    document_id = new_document_id()
    stored_filename = f"{document_id}_{safe_filename}"
    project_dir = resolve_upload_dir(settings) / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    destination = project_dir / stored_filename

    digest = hashlib.sha256()
    size_bytes = 0
    try:
        with destination.open("wb") as output:
            while chunk := await upload_file.read(1024 * 1024):
                size_bytes += len(chunk)
                if size_bytes > settings.upload_max_bytes:
                    raise UploadValidationError(
                        "file_too_large",
                        f"File exceeds maximum size of {settings.upload_max_bytes} bytes",
                    )
                digest.update(chunk)
                output.write(chunk)
    except UploadValidationError:
        destination.unlink(missing_ok=True)
        raise

    if size_bytes == 0:
        destination.unlink(missing_ok=True)
        raise UploadValidationError("empty_file", "Uploaded file is empty")

    return {
        "document_id": document_id,
        "original_filename": original_filename,
        "stored_filename": stored_filename,
        "size_bytes": size_bytes,
        "checksum_sha256": digest.hexdigest(),
        "storage_path": str(destination),
    }
