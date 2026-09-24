import base64

import pytest

from agent_factures.agent.documents import DocumentError, load_document


def test_pdf_becomes_document_block(tmp_path):
    path = tmp_path / "f.PDF"
    path.write_bytes(b"%PDF-1.4 fake")
    block = load_document(path)
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"
    assert base64.standard_b64decode(block["source"]["data"]) == b"%PDF-1.4 fake"


@pytest.mark.parametrize(("suffix", "media_type"), [(".png", "image/png"), (".jpg", "image/jpeg"), (".jpeg", "image/jpeg")])
def test_images_become_image_blocks(tmp_path, suffix, media_type):
    path = tmp_path / f"scan{suffix}"
    path.write_bytes(b"img")
    block = load_document(path)
    assert block["type"] == "image"
    assert block["source"]["media_type"] == media_type


def test_unsupported_format_raises(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("x")
    with pytest.raises(DocumentError, match="Format non supporté"):
        load_document(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(DocumentError, match="illisible"):
        load_document(tmp_path / "absent.pdf")
