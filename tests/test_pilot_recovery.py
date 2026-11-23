from base64 import b64encode

import pytest

from deploy import pilot


def test_restore_document_key_rejects_malformed_input_before_touching_volume(monkeypatch, tmp_path):
    directory = tmp_path / "app"
    directory.mkdir()
    key = directory / "document-key"
    key.write_text("original", encoding="ascii")
    monkeypatch.setattr(pilot, "ROOT", tmp_path)

    with pytest.raises(ValueError, match="32-byte"):
        pilot.restore_document_key("invalid")
    assert key.read_text(encoding="ascii") == "original"
    assert list(directory.iterdir()) == [key]


def test_restore_document_key_replaces_existing_key_without_partial_files(monkeypatch, tmp_path):
    directory = tmp_path / "app"
    directory.mkdir()
    key = directory / "document-key"
    key.write_text("original", encoding="ascii")
    monkeypatch.setattr(pilot, "ROOT", tmp_path)
    monkeypatch.setattr(pilot.os, "chown", lambda *_: None, raising=False)
    material = b64encode(bytes(range(32))).decode()

    pilot.restore_document_key(material + "\r\n")
    assert key.read_text(encoding="ascii") == material + "\n"
    key.chmod(0o600)
    assert list(directory.iterdir()) == [key]
