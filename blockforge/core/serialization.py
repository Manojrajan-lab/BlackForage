"""Canonical binary serialization for BlockForge consensus objects.

Rules (consensus-critical):
  * Integers are unsigned, fixed-width, big-endian. No varints, no negatives.
  * Variable-length data is prefixed by a uint32 length and bounded by a
    caller-supplied maximum.
  * Decoding must consume the input exactly; trailing bytes are an error.
  * Booleans, floats and text are intentionally unsupported.

Because each object has exactly one valid encoding, hashes and signatures
computed over these bytes are identical on every node.
"""
from __future__ import annotations


class SerializationError(ValueError):
    """Raised on any malformed, truncated, oversized or non-canonical input."""


class Writer:
    """Append-only canonical encoder."""

    __slots__ = ("_buf",)

    def __init__(self) -> None:
        self._buf = bytearray()

    def _uint(self, value: int, size: int) -> "Writer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise SerializationError("integer required")
        if value < 0 or value >= (1 << (8 * size)):
            raise SerializationError(f"value out of range for uint{size * 8}")
        self._buf += value.to_bytes(size, "big")
        return self

    def u8(self, value: int) -> "Writer":
        return self._uint(value, 1)

    def u16(self, value: int) -> "Writer":
        return self._uint(value, 2)

    def u32(self, value: int) -> "Writer":
        return self._uint(value, 4)

    def u64(self, value: int) -> "Writer":
        return self._uint(value, 8)

    def fixed(self, data: bytes, size: int) -> "Writer":
        """Write exactly `size` bytes (e.g. hashes, public keys)."""
        if not isinstance(data, (bytes, bytearray)) or len(data) != size:
            raise SerializationError(f"expected exactly {size} bytes")
        self._buf += data
        return self

    def var_bytes(self, data: bytes, max_len: int) -> "Writer":
        """Write uint32 length + data; data length must be <= max_len."""
        if not isinstance(data, (bytes, bytearray)):
            raise SerializationError("bytes required")
        if len(data) > max_len:
            raise SerializationError("field exceeds maximum length")
        self.u32(len(data))
        self._buf += data
        return self

    def getvalue(self) -> bytes:
        return bytes(self._buf)

    def __len__(self) -> int:
        return len(self._buf)


class Reader:
    """Strict canonical decoder over an immutable byte string."""

    __slots__ = ("_data", "_pos")

    def __init__(self, data: bytes) -> None:
        if not isinstance(data, (bytes, bytearray)):
            raise SerializationError("bytes required")
        self._data = bytes(data)
        self._pos = 0

    @property
    def remaining(self) -> int:
        return len(self._data) - self._pos

    def _take(self, n: int) -> bytes:
        if n < 0 or n > self.remaining:
            raise SerializationError("unexpected end of data")
        chunk = self._data[self._pos:self._pos + n]
        self._pos += n
        return chunk

    def u8(self) -> int:
        return int.from_bytes(self._take(1), "big")

    def u16(self) -> int:
        return int.from_bytes(self._take(2), "big")

    def u32(self) -> int:
        return int.from_bytes(self._take(4), "big")

    def u64(self) -> int:
        return int.from_bytes(self._take(8), "big")

    def fixed(self, size: int) -> bytes:
        return self._take(size)

    def var_bytes(self, max_len: int) -> bytes:
        length = self.u32()
        # Check bounds BEFORE slicing so a hostile length cannot cause allocation.
        if length > max_len:
            raise SerializationError("field exceeds maximum length")
        return self._take(length)

    def finish(self) -> None:
        """Assert all input was consumed (rejects trailing garbage)."""
        if self.remaining != 0:
            raise SerializationError("trailing bytes after object")