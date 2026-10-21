import pytest

from blockforge.consensus.params import COIN, DEV
from blockforge.mempool.mempool import MempoolError


def test_admit_select_and_confirm(node, helpers, alice, bob):
    helpers.mine_blocks(node, alice.key_hash, 1)
    t0 = alice.sign_transfer(bob.address, 1_000, 10, 0)
    t1 = alice.sign_transfer(bob.address, 2_000, 20, 1)
    node.submit_transaction(t0)
    node.submit_transaction(t1)
    assert node.get_account(alice.key_hash)["next_nonce"] == 2
    picked, fees = node.mempool.select_for_block(10_000, 10)
    assert [t.nonce for t in picked] == [0, 1] and fees == 30
    helpers.mine_next(node, alice.key_hash)           # template pulls both from the pool
    assert len(node.mempool) == 0
    assert node.get_account(bob.key_hash)["balance"] == 3_000
    found = node.get_transaction(t0.txid)
    assert found["confirmed"] and found["height"] == node.tip()[0]


@pytest.mark.parametrize("build,code", [
    (lambda a, b, n: a.sign_transfer(b.address, 1, DEV.min_fee, 5), "nonce-gap"),
    (lambda a, b, n: a.sign_transfer(b.address, 10_000 * COIN, DEV.min_fee, 0), "insufficient-funds"),
])
def test_rejections(node, helpers, alice, bob, build, code):
    helpers.mine_blocks(node, alice.key_hash, 1)
    with pytest.raises(MempoolError) as exc:
        node.submit_transaction(build(alice, bob, node))
    assert exc.value.code == code


def test_duplicate_stale_and_unfunded(node, helpers, alice, bob):
    helpers.mine_blocks(node, alice.key_hash, 1)
    tx = alice.sign_transfer(bob.address, 1, DEV.min_fee, 0)
    node.submit_transaction(tx)
    with pytest.raises(MempoolError) as dup:
        node.submit_transaction(tx)
    assert dup.value.code == "duplicate"
    helpers.mine_next(node, alice.key_hash)
    stale = alice.sign_transfer(bob.address, 2, DEV.min_fee, 0)
    with pytest.raises(MempoolError) as old:
        node.submit_transaction(stale)
    assert old.value.code == "stale-nonce"
    with pytest.raises(MempoolError) as poor:         # bob never mined; only has 1 base unit
        node.submit_transaction(bob.sign_transfer(alice.address, 5, DEV.min_fee, 0))
    assert poor.value.code == "insufficient-funds"


def test_replace_by_fee(node, helpers, alice, bob):
    helpers.mine_blocks(node, alice.key_hash, 1)
    low = alice.sign_transfer(bob.address, 1, 100, 0)
    node.submit_transaction(low)
    weak = alice.sign_transfer(bob.address, 2, 105, 0)       # < +10%
    with pytest.raises(MempoolError):
        node.submit_transaction(weak)
    strong = alice.sign_transfer(bob.address, 2, 200, 0)
    node.submit_transaction(strong)
    assert low.txid not in node.mempool and strong.txid in node.mempool


def test_coinbase_never_enters_pool(node, helpers, alice):
    cb = helpers.mine_next(node, alice.key_hash).transactions[0]
    with pytest.raises(MempoolError):
        node.mempool.add(cb)


def test_mining_thread_finds_real_blocks(node, alice):
    import time
    node.start_mining(alice.key_hash)
    deadline = time.time() + 20
    while node.tip()[0] < 3 and time.time() < deadline:
        time.sleep(0.05)
    node.stop_mining()
    assert node.tip()[0] >= 3 and not node.is_mining()
    assert node.get_account(alice.key_hash)["balance"] >= 3 * 50 * COIN