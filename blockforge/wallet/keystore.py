"""Encrypted private-key storage.

Format (JSON, version 1):
  scrypt(password, salt, n, r, p) -> 32-byte key -> AES-256-GCM(secret)
The address and public key are bound into the GCM authenticated data, so a
tampered file fails to decrypt. Files are written atomically with mode 0600.
The private key is never written in plaintext and never returned by any API.
"""
from __future__ import annotations

import json
import os
import secrets
from typing import Any, Dict

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

KEYSTORE_VERSION = 1
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
MIN_SCRYPT_N, MAX_SCRYPT_N = 2 ** 14, 2 ** 20
MIN_PASSWORD_LEN = 8


class KeystoreError(ValueError):
    """Raised for bad passwords, corrupt files or unsafe parameters."""


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(password.encode("utf-8"))


def _aad(address: str, pubkey_hex: str) -> bytes:
    return f"BlockForge/keystore/v1|{address}|{pubkey_hex}".encode("ascii")


def encrypt_key(secret: bytes, password: str, address: str, pubkey_hex: str,
                n: int = SCRYPT_N) -> Dict[str, Any]:
    if len(secret) != 32:
        raise KeystoreError("secret must be 32 bytes")
    if len(password) < MIN_PASSWORD_LEN:
        raise KeystoreError(f"password must be at least {MIN_PASSWORD_LEN} characters")
    if not MIN_SCRYPT_N <= n <= MAX_SCRYPT_N:
        raise KeystoreError("scrypt cost out of range")
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    key = _derive(password, salt, n, SCRYPT_R, SCRYPT_P)
    ciphertext = AESGCM(key).encrypt(nonce, secret, _aad(address, pubkey_hex))
    return {
        "version": KEYSTORE_VERSION,
        "address": address,
        "public_key": pubkey_hex,
        "kdf": {"name": "scrypt", "n": n, "r": SCRYPT_R, "p": SCRYPT_P, "salt": salt.hex()},
        "cipher": {"name": "aes-256-gcm", "nonce": nonce.hex(), "ciphertext": ciphertext.hex()},
    }


def decrypt_key(blob: Dict[str, Any], password: str) -> bytes:
    try:
        if blob["version"] != KEYSTORE_VERSION:
            raise KeystoreError("unsupported keystore version")
        kdf, cipher = blob["kdf"], blob["cipher"]
        if kdf["name"] != "scrypt" or cipher["name"] != "aes-256-gcm":
            raise KeystoreError("unsupported keystore algorithms")
        n, r, p = int(kdf["n"]), int(kdf["r"]), int(kdf["p"])
        if not MIN_SCRYPT_N <= n <= MAX_SCRYPT_N or r != SCRYPT_R or p != SCRYPT_P:
            raise KeystoreError("unsafe scrypt parameters")
        salt = bytes.fromhex(kdf["salt"])
        nonce = bytes.fromhex(cipher["nonce"])
        ciphertext = bytes.fromhex(cipher["ciphertext"])
        aad = _aad(blob["address"], blob["public_key"])
    except KeystoreError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise KeystoreError("corrupt keystore file") from exc
    key = _derive(password, salt, n, r, p)
    try:
        secret = AESGCM(key).decrypt(nonce, ciphertext, aad)
    except InvalidTag as exc:
        raise KeystoreError("wrong password or corrupted keystore") from exc
    if len(secret) != 32:
        raise KeystoreError("corrupt keystore file")
    return secret


def save_keystore(path: str, blob: Dict[str, Any]) -> None:
    """Atomic write, owner-only permissions. Refuses to overwrite an existing file."""
    if os.path.exists(path):
        raise KeystoreError(f"refusing to overwrite existing file {path}")
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp{secrets.token_hex(4)}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(blob, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.link(tmp, path)  # fails if path appeared meanwhile; no silent overwrite
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def load_keystore(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            blob = json.load(fh)
    except (OSError, ValueError) as exc:
        raise KeystoreError(f"cannot read keystore: {exc}") from exc
    if not isinstance(blob, dict):
        raise KeystoreError("corrupt keystore file")
    return blob