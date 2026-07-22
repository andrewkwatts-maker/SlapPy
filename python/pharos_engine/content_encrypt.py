"""Content encryption for packaged distributions.

Uses AES-256-GCM (via the standard library's `hashlib` + `os.urandom` + optionally
`cryptography` if installed; falls back to XOR obfuscation otherwise).

Usage:
    from pharos_engine.content_encrypt import encrypt_dir, decrypt_file, derive_key

    key = derive_key("my-secret-passphrase")
    encrypt_dir("assets/", "dist/assets_enc/", key)
    data = decrypt_file("dist/assets_enc/sprites/car.png.enc", key)
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Callable

import yaml


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------


def derive_key(
    passphrase: str, salt: bytes | None = None
) -> tuple[bytes, bytes]:
    """Derive a 32-byte AES-256 key from a human-readable *passphrase*.

    PBKDF2-HMAC-SHA256 is used rather than a raw hash because it is
    deliberately slow (100 000 iterations), making brute-force attacks
    computationally expensive even when the passphrase is weak.

    Returns:
        (key_bytes, salt) — both needed to reproduce the same key later.
        Store the salt alongside the encrypted content (it is not secret).
    """
    if salt is None:
        salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac(
        hash_name="sha256",
        password=passphrase.encode("utf-8"),
        salt=salt,
        iterations=100_000,
        dklen=32,
    )
    return key, salt


# ---------------------------------------------------------------------------
# Low-level encrypt / decrypt
# ---------------------------------------------------------------------------


def _has_cryptography() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def _xor_keystream(data: bytes, key: bytes) -> bytes:
    """XOR *data* against a SHA-256-derived keystream seeded by *key*.

    Not military-grade, but sufficient for light obfuscation when the
    ``cryptography`` package is unavailable (e.g. minimal CI environments).
    The keystream is produced by repeatedly hashing the key + a counter so
    it can be reproduced exactly on decryption.
    """
    result = bytearray(len(data))
    block_size = 32  # SHA-256 output size
    offset = 0
    counter = 0
    while offset < len(data):
        block = hashlib.sha256(key + counter.to_bytes(4, "little")).digest()
        chunk = min(block_size, len(data) - offset)
        for i in range(chunk):
            result[offset + i] = data[offset + i] ^ block[i]
        offset += chunk
        counter += 1
    return bytes(result)


def encrypt_bytes(data: bytes, key: bytes) -> bytes:
    """Encrypt *data* with AES-256-GCM using *key*.

    A fresh 12-byte nonce is generated for every call and prepended to the
    returned ciphertext so that :func:`decrypt_bytes` can recover it without
    any additional metadata.

    Falls back to XOR obfuscation when ``cryptography`` is not installed.
    """
    nonce = os.urandom(12)
    if _has_cryptography():
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        ct = AESGCM(key).encrypt(nonce, data, None)
    else:
        # XOR fallback: incorporate the nonce into the key so different
        # invocations produce different ciphertext even for identical plaintext.
        ct = _xor_keystream(data, key + nonce)
    return nonce + ct


def decrypt_bytes(data: bytes, key: bytes) -> bytes:
    """Decrypt ciphertext produced by :func:`encrypt_bytes`.

    The leading 12 bytes are the nonce; the remainder is the ciphertext
    (plus a 16-byte GCM authentication tag when AES-GCM was used).
    """
    nonce, ct = data[:12], data[12:]
    if _has_cryptography():
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM(key).decrypt(nonce, ct, None)
    return _xor_keystream(ct, key + nonce)


# ---------------------------------------------------------------------------
# File-level helpers
# ---------------------------------------------------------------------------


def encrypt_file(src: str | Path, dst: str | Path, key: bytes) -> None:
    """Read *src*, encrypt it, and write the result to *dst*.

    If *dst* has no ``.enc`` extension it is appended automatically so the
    file is distinguishable from plaintext on disk.
    """
    src = Path(src)
    dst = Path(dst)
    if dst.suffix != ".enc":
        dst = dst.with_suffix(dst.suffix + ".enc")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(encrypt_bytes(src.read_bytes(), key))


def decrypt_file(src: str | Path, key: bytes) -> bytes:
    """Read the encrypted file at *src* and return the decrypted bytes."""
    return decrypt_bytes(Path(src).read_bytes(), key)


# ---------------------------------------------------------------------------
# Directory-level helpers
# ---------------------------------------------------------------------------


def encrypt_dir(
    src_dir: str | Path,
    dst_dir: str | Path,
    key: bytes,
    extensions: list[str] | None = None,
) -> list[Path]:
    """Encrypt all files under *src_dir*, mirroring the structure in *dst_dir*.

    Args:
        src_dir: Root of the plaintext asset tree.
        dst_dir: Root of the output encrypted tree (created if absent).
        key: 32-byte AES key from :func:`derive_key`.
        extensions: Optional whitelist, e.g. ``[".png", ".wav", ".yml"]``.
            When ``None`` every file is encrypted.

    Returns:
        List of ``Path`` objects for all encrypted files written.
    """
    src_dir = Path(src_dir)
    dst_dir = Path(dst_dir)
    written: list[Path] = []

    for src_file in src_dir.rglob("*"):
        if not src_file.is_file():
            continue
        if extensions is not None and src_file.suffix.lower() not in extensions:
            continue

        rel = src_file.relative_to(src_dir)
        dst_file = dst_dir / rel
        if dst_file.suffix != ".enc":
            dst_file = dst_file.with_suffix(dst_file.suffix + ".enc")

        dst_file.parent.mkdir(parents=True, exist_ok=True)
        dst_file.write_bytes(encrypt_bytes(src_file.read_bytes(), key))
        written.append(dst_file)

    return written


def decrypt_dir(
    src_dir: str | Path,
    dst_dir: str | Path,
    key: bytes,
) -> list[Path]:
    """Decrypt all ``.enc`` files under *src_dir*, writing plaintext to *dst_dir*.

    Returns:
        List of ``Path`` objects for all decrypted files written.
    """
    src_dir = Path(src_dir)
    dst_dir = Path(dst_dir)
    written: list[Path] = []

    for src_file in src_dir.rglob("*.enc"):
        if not src_file.is_file():
            continue

        rel = src_file.relative_to(src_dir)
        # Strip the trailing .enc to recover the original extension.
        dst_file = dst_dir / rel.with_suffix("")
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        dst_file.write_bytes(decrypt_bytes(src_file.read_bytes(), key))
        written.append(dst_file)

    return written


# ---------------------------------------------------------------------------
# High-level asset loader
# ---------------------------------------------------------------------------


class EncryptedAssetLoader:
    """Runtime loader for a directory of encrypted assets.

    Keeps the decryption key in memory and transparently decrypts on access,
    so game code never touches raw ciphertext.

    Example::

        key, _ = derive_key("game-secret")
        loader = EncryptedAssetLoader("dist/assets_enc/", key)
        image_bytes = loader.load("sprites/player.png")
        config = loader.load_yaml("config/levels.yml")
    """

    def __init__(self, root_dir: str | Path, key: bytes) -> None:
        self._root = Path(root_dir)
        self._key = key

    def _resolve(self, relative_path: str) -> Path:
        """Find the encrypted file for *relative_path*, with or without ``.enc``."""
        candidate = self._root / relative_path
        if candidate.exists():
            return candidate
        enc_candidate = Path(str(candidate) + ".enc")
        if enc_candidate.exists():
            return enc_candidate
        raise FileNotFoundError(
            f"Encrypted asset not found: {relative_path!r} "
            f"(looked in {self._root})"
        )

    def load(self, relative_path: str) -> bytes:
        """Decrypt and return the raw bytes of *relative_path*."""
        path = self._resolve(relative_path)
        return decrypt_bytes(path.read_bytes(), self._key)

    def load_text(self, relative_path: str) -> str:
        """Decrypt and decode *relative_path* as a UTF-8 text file."""
        return self.load(relative_path).decode("utf-8")

    def load_yaml(self, relative_path: str) -> dict:
        """Decrypt *relative_path* and parse it as YAML, returning a dict."""
        return yaml.safe_load(self.load_text(relative_path))
