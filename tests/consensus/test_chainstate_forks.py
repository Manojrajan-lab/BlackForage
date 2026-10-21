from dataclasses import replace

import pytest

from blockforge.consensus.params import COIN, DEV
from blockforge.consensus.validation import ValidationError
from blockforge.core import crypto
from blockforge.core.transaction import Transaction
from blockforge.node.fork_choice import ForkChoiceError, Status
from blockforge.storage.chainstate import ChainStateError


def _mine_with_txs(node, helpers, kh, txs):
    return helpers.make_block_on(node, node.tip()[1], kh, txs, extra=b"t")


def test_balances_nonces_and_supply(node, helpers, alice, bob):
    helpers.mine_blocks(node, alice.key_hash, 2)
    start = node.get_account(alice.key_hash)["balance"]
    tx = alice.sign_transfer(bob.address, 5 * COIN, DEV.min_fee, 0)
    block = _mine_with_txs(node, helpers, alice.key_hash, [tx])
    assert node.submit_block(block)[0].status == Status.EXTENDED
    a, b = node.get_account(alice.key_hash), node.get_account(bob.key_hash)
    assert b["balance"] == 5 * COIN
    assert a["nonce"] == 1
    # alice paid amount+fee, then received subsidy+fee as miner: net = subsidy - amount
    assert a["balance"] == start - 5 * COIN + 50 * COIN
    # supply == total subsidy ever issued (fees only move coins around)
    assert node.db.get_total_supply() == 50 * COIN * (node.tip()[0] + 1)


def test_rejects_overspend_bad_nonce_and_inflated_coinbase(node, helpers, alice, bob):
    helpers.mine_blocks(node, alice.key_hash, 1)
    over = alice.sign_transfer(bob.address, 10_000 * COIN, DEV.min_fee, 0)
    with pytest.raises(ChainStateError, match="insufficient-funds"):
        node.submit_block(_mine_with_txs(node, helpers, alice.key_hash, [over]))
    gap = alice.sign_transfer(bob.address, 1, DEV.min_fee, 7)
    with pytest.raises(ChainStateError, match="bad-nonce"):
        node.submit_block(_mine_with_txs(node, helpers, alice.key_hash, [gap]))
    greedy = helpers.make_block_on(node, node.tip()[1], alice.key_hash, [], fees=1)
    with pytest.raises(ChainStateError, match="bad-coinbase-value"):
        node.submit_block(greedy)
    assert node.tip()[0] == 1                        # failed blocks left no trace
    assert node.db.get_total_supply() == 50 * COIN * 2


def test_double_spend_in_one_block_rejected(node, helpers, alice, bob):
    helpers.mine_blocks(node, alice.key_hash, 1)
    t1 = alice.sign_transfer(bob.address, 1, DEV.min_fee, 0)
    t2 = alice.sign_transfer(bob.address, 2, DEV.min_fee, 0)   # same nonce
    with pytest.raises(ChainStateError, match="bad-nonce"):
        node.submit_block(_mine_with_txs(node, helpers, alice.key_hash, [t1, t2]))


def test_invalid_pow_and_duplicate_and_orphan(node, helpers, alice):
    good = helpers.mine_next(node, alice.key_hash)
    assert node.submit_block(good)[0].status == Status.DUPLICATE
    tmpl = node.build_template(alice.key_hash)
    # nonce 0 will (almost surely) not satisfy PoW; scan until we find one that does not
    bad = next(b for b in (tmpl.with_nonce(n) for n in range(5000)) if not b.header.pow_valid())
    with pytest.raises(ValidationError, match="bad-pow"):
        node.submit_block(bad)
    other = helpers.make_block_on(node, good.hash, alice.key_hash, extra=b"x")
    child = helpers.make_block_on(node, good.hash, alice.key_hash, extra=b"y")
    # orphan: block whose parent we have not stored
    from blockforge.core.block import Block
    orphan_hdr = replace(child.header, prev_hash=b"\x09" * 32)
    orphan = Block(orphan_hdr, child.transactions)
    orphan = helpers.solve(orphan)
    assert node.submit_block(orphan)[0].status == Status.ORPHAN


def test_reorg_to_heavier_branch_and_back_state(node, helpers, alice, bob):
    base = helpers.mine_blocks(node, alice.key_hash, 3)
    fork_point = base[-1].hash
    # main branch: one block paying bob via a real transfer
    tx = alice.sign_transfer(bob.address, 1_000, DEV.min_fee, 0)
    main = helpers.make_block_on(node, fork_point, alice.key_hash, [tx], extra=b"main")
    assert node.submit_block(main)[0].status == Status.EXTENDED
    assert node.get_account(bob.key_hash)["balance"] == 1_000
    # competing branch from the same fork point, no transfer, two blocks => heavier
    s1 = helpers.make_block_on(node, fork_point, bob.key_hash, extra=b"s1")
    assert node.submit_block(s1)[0].status == Status.SIDE
    s2 = helpers.make_block_on(node, s1.hash, bob.key_hash, extra=b"s2")
    out = node.submit_block(s2)[0]
    assert out.status == Status.REORG
    assert [b.hash for b in out.reverted] == [main.hash]
    assert [b.hash for b in out.applied] == [s1.hash, s2.hash]
    assert node.tip()[1] == s2.hash
    # transfer undone, bob only has his two miner rewards
    assert node.get_account(bob.key_hash)["balance"] == 100 * COIN
    assert node.get_account(alice.key_hash)["nonce"] == 0
    assert node.db.get_total_supply() == 50 * COIN * (node.tip()[0] + 1)
    # reverted tx is back in the mempool
    assert tx.txid in node.mempool


def test_reorg_with_invalid_block_rolls_back_cleanly(node, helpers, alice, bob):
    base = helpers.mine_blocks(node, alice.key_hash, 2)
    fp = base[-1].hash
    main = helpers.make_block_on(node, fp, alice.key_hash, extra=b"main")
    node.submit_block(main)
    before = (node.tip(), node.get_account(alice.key_hash), node.db.get_total_supply())
    s1 = helpers.make_block_on(node, fp, bob.key_hash, extra=b"s1")
    node.submit_block(s1)
    overspend = bob.sign_transfer(alice.address, 10_000 * COIN, DEV.min_fee, 0)
    bad = helpers.make_block_on(node, s1.hash, bob.key_hash, [overspend], extra=b"bad")
    with pytest.raises(ChainStateError):
        node.submit_block(bad)                       # heavier, but invalid on apply
    after = (node.tip(), node.get_account(alice.key_hash), node.db.get_total_supply())
    assert before == after and node.tip()[1] == main.hash
    assert node.fork_choice.is_invalid(bad.hash)
    with pytest.raises(ForkChoiceError, match="known-invalid"):
        node.submit_block(bad)


def test_block_locator_and_common_height(node, helpers, alice):
    helpers.mine_blocks(node, alice.key_hash, 25)
    loc = node.fork_choice.block_locator()
    assert loc[0] == node.tip()[1] and loc[-1] == node.db.get_active_hash(0)
    assert node.fork_choice.find_common_height(loc) == node.tip()[0]
    assert node.fork_choice.find_common_height([b"\x01" * 32]) is None


def test_persistence_across_restart(make_node, helpers, alice, tmp_path):
    n1 = make_node("persist.db")
    helpers.mine_blocks(n1, alice.key_hash, 4)
    tip, bal = n1.tip(), n1.get_account(alice.key_hash)
    n1.stop()
    from blockforge.node.node import Node
    n2 = Node(DEV, str(tmp_path / "persist.db"))
    n2.start()
    try:
        assert n2.tip() == tip and n2.get_account(alice.key_hash) == bal
    finally:
        n2.stop()


def test_difficulty_retargets_through_the_node(node, helpers, alice):
    from blockforge.consensus.pow import bits_to_target
    n = DEV.retarget_interval
    blocks = helpers.mine_blocks(node, alice.key_hash, 2 * n + 1)   # heights 1 .. 2n+1
    by_height = {b.height: b.header.bits for b in blocks}
    assert len({by_height[h] for h in range(1, n)}) == 1            # constant inside a period
    # genesis is years older than block 1, so the first window looks "slow": already at the
    # easiest allowed target, difficulty cannot drop further
    assert by_height[n] == DEV.initial_bits
    # second window (heights n..2n-1) was mined far faster than target_block_time -> harder
    assert bits_to_target(by_height[2 * n]) < bits_to_target(by_height[2 * n - 1])
    # a block that ignores the new difficulty is rejected
    stale = helpers.make_block_on(node, node.tip()[1], alice.key_hash)
    from dataclasses import replace
    from blockforge.core.block import Block
    expected = node.fork_choice.required_bits_for_child(node.tip()[1])
    wrong = DEV.initial_bits if expected != DEV.initial_bits else 0x1F00FFFF
    bad = Block(replace(stale.header, bits=wrong), stale.transactions)
    with pytest.raises(ValidationError, match="bad-bits"):
        node.submit_block(helpers.solve(bad))