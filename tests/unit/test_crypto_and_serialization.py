import pytest

from blockforge.core import crypto
from blockforge.core.amounts import AmountError, format_amount, to_base_units
from blockforge.core.merkle import merkle_proof, merkle_root, verify_proof
from blockforge.core.serialization import Reader, SerializationError, Writer


def test_sign_verify_roundtrip():
    sk = crypto.generate_private_key()
    pk = crypto.private_to_public(sk)
    h = crypto.sha256d(b"msg")
    sig = crypto.sign(sk, h)
    assert len(sig) == 64 and crypto.is_canonical_signature(sig)
    assert crypto.verify(pk, h, sig)
    assert not crypto.verify(pk, crypto.sha256d(b"other"), sig)


def test_signing_is_deterministic():
    sk = crypto.generate_private_key()
    h = crypto.sha256d(b"x")
    assert crypto.sign(sk, h) == crypto.sign(sk, h)


def test_high_s_signature_rejected():
    sk = crypto.generate_private_key()
    pk = crypto.private_to_public(sk)
    h = crypto.sha256d(b"x")
    sig = crypto.sign(sk, h)
    r = int.from_bytes(sig[:32], "big")
    s = int.from_bytes(sig[32:], "big")
    flipped = r.to_bytes(32, "big") + (crypto.SECP256K1_N - s).to_bytes(32, "big")
    assert not crypto.is_canonical_signature(flipped)
    assert not crypto.verify(pk, h, flipped)


def test_invalid_keys_rejected():
    assert not crypto.is_valid_public_key(b"\x02" + b"\x00" * 32)
    assert not crypto.is_valid_public_key(b"\x04" + b"\x01" * 32)
    with pytest.raises(crypto.CryptoError):
        crypto.private_to_public(b"\x00" * 32)
    with pytest.raises(crypto.CryptoError):
        crypto.private_to_public(b"short")


def test_address_roundtrip_and_checksum():
    pk = crypto.private_to_public(crypto.generate_private_key())
    addr = crypto.pubkey_to_address(pk, "BF")
    assert crypto.address_to_key_hash(addr, "BF") == crypto.pubkey_hash(pk)
    assert crypto.is_valid_address(addr, "BF")
    tampered = addr[:-1] + ("0" if addr[-1] != "0" else "1")
    assert not crypto.is_valid_address(tampered, "BF")
    assert not crypto.is_valid_address(addr[:2] + addr[2:].upper(), "BF")  # lowercase hex only
    assert not crypto.is_valid_address("XX" + addr[2:], "BF")


def test_serialization_strict():
    data = Writer().u8(1).u32(7).var_bytes(b"abc", 10).getvalue()
    r = Reader(data)
    assert (r.u8(), r.u32(), r.var_bytes(10)) == (1, 7, b"abc")
    r.finish()
    r2 = Reader(data + b"\x00")
    r2.u8(), r2.u32(), r2.var_bytes(10)
    with pytest.raises(SerializationError):
        r2.finish()
    with pytest.raises(SerializationError):
        Reader(Writer().u32(1000).getvalue()).var_bytes(10)  # hostile length
    with pytest.raises(SerializationError):
        Writer().u8(256)
    with pytest.raises(SerializationError):
        Writer().u8(-1)
    with pytest.raises(SerializationError):
        Writer().u8(True)


def test_merkle_properties():
    ids = [crypto.sha256(bytes([i])) for i in range(5)]
    root = merkle_root(ids)
    for i, t in enumerate(ids):
        assert verify_proof(t, merkle_proof(ids, i), root)
    assert not verify_proof(ids[0], merkle_proof(ids, 1), root)
    # odd node is promoted, not duplicated: [a,b,c] != [a,b,c,c]
    assert merkle_root(ids[:3]) != merkle_root(ids[:3] + [ids[2]])
    with pytest.raises(ValueError):
        merkle_root([])


def test_amounts_exact():
    assert to_base_units("1") == 100_000_000
    assert to_base_units("0.00000001") == 1
    assert format_amount(150_000_000) == "1.50000000"
    for bad in ("-1", "1e3", "0.000000001", "", "1.2.3", "abc", " "):
        with pytest.raises(AmountError):
            to_base_units(bad)
    with pytest.raises(AmountError):
        to_base_units("999999999999999999999")