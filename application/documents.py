"""Protect authorization documents before storing them in PostgreSQL."""

from base64 import b64decode
from binascii import Error as Base64Error
from hashlib import sha256
from os import urandom
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from application.access import AccessError


MAX_DOCUMENT_SIZE = 1024 * 1024


class DocumentCipher:
    def __init__(self, encoded_key: str) -> None:
        try:
            key = b64decode(encoded_key, validate=True)
        except (Base64Error, ValueError):
            key = b""
        if len(key) != 32:
            raise ValueError("PENTEST_AGENT_DOCUMENT_KEY must be a base64-encoded 32-byte key")
        self.cipher = AESGCM(key)

    @staticmethod
    def _context(org_id: UUID, project_id: UUID, document_id: UUID, digest: str) -> bytes:
        return b"pentest-agent:authorization:pdf:v1:" + org_id.bytes + project_id.bytes + document_id.bytes + bytes.fromhex(digest)

    def encrypt(self, org_id: UUID, project_id: UUID, document_id: UUID, payload: bytes) -> tuple[str, bytes, bytes]:
        if len(payload) > MAX_DOCUMENT_SIZE:
            raise AccessError(413, "document_too_large")
        if not payload.startswith(b"%PDF-"):
            raise AccessError(422, "invalid_document")
        digest, nonce = sha256(payload).hexdigest(), urandom(12)
        associated_data = self._context(org_id, project_id, document_id, digest)
        return digest, nonce, self.cipher.encrypt(nonce, payload, associated_data)

    def decrypt(self, org_id: UUID, project_id: UUID, document_id: UUID, digest: str,
                nonce: bytes, ciphertext: bytes) -> bytes:
        try:
            payload = self.cipher.decrypt(nonce, ciphertext, self._context(org_id, project_id, document_id, digest))
        except (InvalidTag, ValueError):
            raise AccessError(503, "document_unavailable") from None
        if sha256(payload).hexdigest() != digest:
            raise AccessError(503, "document_unavailable")
        return payload

    @staticmethod
    def _evidence_context(org_id: UUID, project_id: UUID, evidence_id: UUID,
                          permission_id: UUID, revision: int, source_digest: str) -> bytes:
        return (b"pentest-agent:evidence:projection:v1:" + org_id.bytes + project_id.bytes + evidence_id.bytes
                + permission_id.bytes + revision.to_bytes(4, "big") + bytes.fromhex(source_digest))

    def encrypt_evidence(self, org_id: UUID, project_id: UUID, evidence_id: UUID, permission_id: UUID,
                         revision: int, source_digest: str, projection: bytes) -> tuple[bytes, bytes]:
        context = self._evidence_context(org_id, project_id, evidence_id, permission_id, revision, source_digest)
        nonce = urandom(12)
        return nonce, self.cipher.encrypt(nonce, projection, context)

    def decrypt_evidence(self, org_id: UUID, project_id: UUID, evidence_id: UUID, permission_id: UUID,
                         revision: int, source_digest: str, nonce: bytes, ciphertext: bytes) -> bytes:
        context = self._evidence_context(org_id, project_id, evidence_id, permission_id, revision, source_digest)
        try:
            return self.cipher.decrypt(nonce, ciphertext, context)
        except InvalidTag:
            raise AccessError(503, "evidence_unavailable") from None
