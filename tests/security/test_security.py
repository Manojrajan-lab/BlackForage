import pytest
from fastapi.testclient import TestClient

from blockforge.api.app import create_app
from blockforge.api.security import RateLimiter
from blockforge.config import Settings
from blockforge.consensus.params import DEV
from blockforge.network import messages as m


def test_rate_limiter_bucket():
    rl = RateLimiter(per_minute=3)
    assert [rl.allow("ip", now=0.0) for _ in range(4)] == [True, True, True, False]
    assert rl.allow("ip", now=21.0)            # refills 1 token per 20s
    assert rl.allow("other", now=0.0)


def test_rate_limit_and_body_limits_over_http(node, tmp_path):
    settings = Settings(data_dir=str(tmp_path), p2p_enabled=False, rate_limit_per_minute=5,
                        tx_rate_limit_per_minute=2, max_body_bytes=2_000)
    with TestClient(create_app(settings, node=node, enable_p2p=False)) as c:
        big = c.post("/v1/transactions", json={"hex": "00" * 5_000})
        assert big.status_code == 413
        codes = [c.get("/health").status_code for _ in range(8)]
        assert 429 in codes
    # security headers present on normal responses
    settings2 = Settings(data_dir=str(tmp_path), p2p_enabled=False)
    with TestClient(create_app(settings2, node=node, enable_p2p=False)) as c:
        h = c.get("/health").headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"


def test_tx_endpoint_has_its_own_limit(node, tmp_path):
    settings = Settings(data_dir=str(tmp_path), p2p_enabled=False,
                        rate_limit_per_minute=10_000, tx_rate_limit_per_minute=2)
    with TestClient(create_app(settings, node=node, enable_p2p=False)) as c:
        codes = [c.post("/v1/transactions", json={"hex": "00"}).status_code for _ in range(4)]
        assert codes[:2] == [400, 400] and codes[2:] == [429, 429]


# ------------------------------------------------------------ wire protocol
MAGIC = m.network_magic(DEV.chain_id)


def test_frame_roundtrip_and_magic():
    frame = m.encode_message(MAGIC, m.Ping(42))
    cmd, length, checksum = m.parse_header(MAGIC, frame[:m.HEADER_LEN])
    msg = m.decode_payload(cmd, checksum, frame[m.HEADER_LEN:])
    assert msg == m.Ping(42) and length == 8
    with pytest.raises(m.MessageError):
        m.parse_header(m.network_magic(1), frame[:m.HEADER_LEN])      # other network


def test_corrupt_and_hostile_frames_rejected():
    frame = bytearray(m.encode_message(MAGIC, m.Ping(1)))
    frame[-1] ^= 1
    cmd, _, checksum = m.parse_header(MAGIC, bytes(frame[:m.HEADER_LEN]))
    with pytest.raises(m.MessageError, match="checksum"):
        m.decode_payload(cmd, checksum, bytes(frame[m.HEADER_LEN:]))
    huge = bytearray(m.encode_message(MAGIC, m.Verack()))
    huge[16:20] = (m.MAX_PAYLOAD + 1).to_bytes(4, "big")
    with pytest.raises(m.MessageError, match="too large"):
        m.parse_header(MAGIC, bytes(huge[:m.HEADER_LEN]))
    unknown = bytearray(m.encode_message(MAGIC, m.Verack()))
    unknown[4:16] = b"evil".ljust(12, b"\x00")
    with pytest.raises(m.MessageError, match="unknown"):
        m.parse_header(MAGIC, bytes(unknown[:m.HEADER_LEN]))
    padded = bytearray(m.encode_message(MAGIC, m.Verack()))
    padded[4:16] = b"verack\x00\x00\x00\x00\x00X"
    with pytest.raises(m.MessageError, match="padding"):
        m.parse_header(MAGIC, bytes(padded[:m.HEADER_LEN]))


def test_oversized_collections_rejected():
    with pytest.raises(m.MessageError):
        m.Inv(tuple((m.INV_TX, b"\x00" * 32) for _ in range(m.MAX_INV_ITEMS + 1))).encode_payload()
    from blockforge.core.serialization import SerializationError, Writer
    payload = Writer().u16(m.MAX_INV_ITEMS + 1).getvalue()
    with pytest.raises(m.MessageError):
        m.Inv.decode_payload(payload)
    with pytest.raises(SerializationError):
        m.Version.decode_payload(b"\x00")