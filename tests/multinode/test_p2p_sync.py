"""Two or three real nodes talking over real localhost TCP sockets."""
import asyncio

import pytest

from blockforge.consensus.params import DEV
from blockforge.network.p2p import P2PNetwork


async def wait_for(predicate, timeout=20.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


async def start_net(node):
    net = P2PNetwork(node, host="127.0.0.1", port=0, allow_private=True)
    await net.start()
    return net


async def link(a, b):
    await b.connect_to("127.0.0.1", a.listen_port)
    assert await wait_for(lambda: a.peer_count() >= 1 and b.peer_count() >= 1)


async def test_initial_block_download(make_node, helpers, alice):
    a, b = make_node("a.db"), make_node("b.db")
    await asyncio.to_thread(helpers.mine_blocks, a, alice.key_hash, 8)
    na, nb = await start_net(a), await start_net(b)
    try:
        await link(na, nb)
        assert await wait_for(lambda: b.tip()[0] == 8)
        assert b.tip()[1] == a.tip()[1]
        assert b.get_account(alice.key_hash) == a.get_account(alice.key_hash)
        assert b.db.get_total_supply() == a.db.get_total_supply()
    finally:
        await nb.stop()
        await na.stop()


async def test_transaction_and_block_relay(make_node, helpers, alice, bob):
    a, b = make_node("a.db"), make_node("b.db")
    await asyncio.to_thread(helpers.mine_blocks, a, alice.key_hash, 2)
    na, nb = await start_net(a), await start_net(b)
    try:
        await link(na, nb)
        assert await wait_for(lambda: b.tip()[0] == 2)
        tx = alice.sign_transfer(bob.address, 1_000, DEV.min_fee, 0)
        await asyncio.to_thread(a.submit_transaction, tx)
        assert await wait_for(lambda: tx.txid in b.mempool)       # tx gossip
        block = await asyncio.to_thread(helpers.mine_next, b, bob.key_hash)
        assert await wait_for(lambda: a.tip()[1] == block.hash)   # block gossip back to A
        assert tx.txid not in a.mempool and a.get_account(bob.key_hash)["balance"] >= 1_000
    finally:
        await nb.stop()
        await na.stop()


async def test_other_network_is_rejected(make_node, helpers, tmp_path):
    from blockforge.consensus.params import TESTNET
    from blockforge.node.node import Node
    a = make_node("a.db")
    other = Node(TESTNET, str(tmp_path / "t.db"))
    other.start()
    na = await start_net(a)
    nt = P2PNetwork(other, host="127.0.0.1", port=0, allow_private=True)
    await nt.start()
    try:
        await nt.connect_to("127.0.0.1", na.listen_port)
        await asyncio.sleep(1.0)
        assert na.peer_count() == 0 and nt.peer_count() == 0
    finally:
        await nt.stop()
        await na.stop()
        other.stop()


async def test_longest_chain_wins_after_partition(make_node, helpers, alice, bob):
    a, b = make_node("a.db"), make_node("b.db")
    await asyncio.to_thread(helpers.mine_blocks, a, alice.key_hash, 2)
    await asyncio.to_thread(helpers.mine_blocks, b, bob.key_hash, 5)   # independent, heavier
    na, nb = await start_net(a), await start_net(b)
    try:
        await link(na, nb)
        assert await wait_for(lambda: a.tip()[1] == b.tip()[1] and a.tip()[0] == 5)
        assert a.get_account(alice.key_hash)["balance"] == 0          # A's old branch was reorged out
        assert a.get_account(bob.key_hash)["balance"] == 5 * 50 * 10 ** 8
    finally:
        await nb.stop()
        await na.stop()