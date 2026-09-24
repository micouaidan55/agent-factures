"""Transforme un fichier en bloc de contenu pour l'API Messages."""

import base64
from pathlib import Path

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


class DocumentError(ValueError):
    pass


def load_document(path: Path) -> dict:
    media_type = MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        raise DocumentError(f"Format non supporté : {path.suffix or 'sans extension'} (formats acceptés : PDF, PNG, JPG).")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DocumentError(f"Fichier illisible : {path.name} ({exc.strerror}).") from exc
    block_type = "document" if media_type == "application/pdf" else "image"
    return {
        "type": block_type,
        "source": {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(raw).decode("ascii")},
    }
