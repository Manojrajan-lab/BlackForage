from dataclasses import replace

import pytest

from blockforge.consensus.params import DEV, MAINNET
from blockforge.consensus.pow import (bits_to_target, hash_meets_target, mine,
                                      target_to_bits, verify_pow, work_from_bits)
from blockforge.core import crypto
from blockforge.core.block import Block, BlockFormatError, BlockHeader, ZERO_HASH
from blockforge.core.transaction import (KIND_TRANSFER, Transaction,
                                         TransactionError)


@pytest.fixture
def tx(alice, bob):
    return alice.sign_transfer(bob.address, 1_000, DEV.min_fee, 0, b"hi")


def test_tx_roundtrip_and_ids(tx):
    again = Transaction.deserialize(tx.serialize())
    assert again == tx and again.txid == tx.txid
    assert Transaction.from_hex(tx.to_hex()) == tx
    tx.validate_stateless(DEV)


def test_tx_trailing_and_truncated_bytes_rejected(tx):
    with pytest.raises(TransactionError):
        Transaction.deserialize(tx.serialize() + b"\x00")
    with pytest.raises(TransactionError):
        Transaction.deserialize(tx.serialize()[:-1])
    with pytest.raises(TransactionError):
        Transaction.from_hex(tx.to_hex().upper())


@pytest.mark.parametrize("field,value,msg", [
    ("amount", 2_000, "invalid signature"),       # any change breaks the signature
    ("fee", 99, "invalid signature"),
    ("nonce", 5, "invalid signature"),
    ("recipient", b"\x01" * 20, "invalid signature"),
    ("chain_id", 1, "wrong chain_id"),
])
def test_tx_tamper_detected(tx, field, value, msg):
    bad = replace(tx, **{field: value})
    with pytest.raises(TransactionError, match=msg):
        bad.validate_stateless(DEV)


def test_replay_on_other_network_rejected(alice, bob):
    tx_main = Transaction.create_transfer(
        alice._secret, MAINNET, crypto.pubkey_hash(bob.public_key), 1, MAINNET.min_fee, 0)
    tx_main.validate_stateless(MAINNET)
    with pytest.raises(TransactionError):
        tx_main.validate_stateless(DEV)


def test_tx_rules(alice, bob):
    with pytest.raises(Exception):
        alice.sign_transfer(bob.address, 0, DEV.min_fee, 0)       # zero amount
    with pytest.raises(Exception):
        alice.sign_transfer(bob.address, 1, DEV.min_fee - 1, 0)   # fee floor
    with pytest.raises(Exception):
        alice.sign_transfer(bob.address, 1, DEV.min_fee, 0, b"x" * 101)  # memo
    cb = Transaction.create_coinbase(DEV, 3, crypto.pubkey_hash(bob.public_key), 5)
    cb.validate_stateless(DEV)
    assert cb.is_coinbase and cb.sender_key_hash is None
    with pytest.raises(TransactionError):
        replace(cb, fee=1).validate_stateless(DEV)
    with pytest.raises(TransactionError):
        replace(cb, kind=9).validate_stateless(DEV)


def test_pow_compact_target_roundtrip():
    for bits in (0x2000FFFF, 0x1F00FFFF, 0x1D00FFFF):
        assert target_to_bits(bits_to_target(bits)) == bits
    with pytest.raises(ValueError):
        bits_to_target(0x20800000)            # negative flag
    assert work_from_bits(0x1F00FFFF) > work_from_bits(0x2000FFFF)


def test_mine_and_verify():
    prefix = b"\x07" * 88
    nonce, digest = mine(prefix, DEV.initial_bits)
    assert verify_pow(prefix, nonce, DEV.initial_bits)
    assert hash_meets_target(digest, DEV.initial_bits)
    assert not hash_meets_target(b"\xff" * 32, DEV.initial_bits)


def test_block_roundtrip_and_tamper(tx, bob):
    cb = Transaction.create_coinbase(DEV, 1, crypto.pubkey_hash(bob.public_key), 50)
    blk = Block.build(1, ZERO_HASH, 1_700_000_001, DEV.initial_bits, 1, [cb, tx])
    assert blk.merkle_root_valid()
    again = Block.deserialize(blk.serialize(), Transaction.deserialize)
    assert again.hash == blk.hash and again.transactions == blk.transactions
    with pytest.raises(BlockFormatError):
        Block.deserialize(blk.serialize() + b"\x00", Transaction.deserialize)
    with pytest.raises(BlockFormatError):
        Block.deserialize(blk.serialize()[:-3], Transaction.deserialize)
    swapped = Block(blk.header, (cb,))
    assert not swapped.merkle_root_valid()
    with pytest.raises(BlockFormatError):
        BlockHeader(1, b"\x00" * 31, b"\x00" * 32, 0, 0, 0)