from base64 import b64encode
from hashlib import sha256
from uuid import uuid4

import pytest

from application.access import AccessError
from application.documents import DocumentCipher


def test_encrypted_document_is_bound_to_its_context():
    cipher = DocumentCipher(b64encode(b"a" * 32).decode())
    org, project, document = uuid4(), uuid4(), uuid4()
    payload = b"%PDF-1.7\nSynthetic document\n%%EOF"
    digest, nonce, encrypted = cipher.encrypt(org, project, document, payload)
    assert sha256(payload).hexdigest() == digest
    assert payload not in encrypted
    assert cipher.decrypt(org, project, document, digest, nonce, encrypted) == payload

    changes = [
        (uuid4(), project, document, digest, nonce, encrypted),
        (org, uuid4(), document, digest, nonce, encrypted),
        (org, project, uuid4(), digest, nonce, encrypted),
        (org, project, document, "0" * 64, nonce, encrypted),
        (org, project, document, digest, nonce, bytes([encrypted[0] ^ 1]) + encrypted[1:]),
    ]
    for args in changes:
        with pytest.raises(AccessError, match="document_unavailable"):
            cipher.decrypt(*args)


@pytest.mark.parametrize("configured_key", ["invalid", b64encode(b"short").decode()])
def test_document_key_must_decode_to_32_bytes(configured_key):
    with pytest.raises(ValueError, match="32-byte key"):
        DocumentCipher(configured_key)
