import pytest
from fastapi.testclient import TestClient

from blockforge.api.app import create_app
from blockforge.config import Settings
from blockforge.consensus.params import DEV

KEY = "k" * 24


@pytest.fixture
def client(node, tmp_path):
    settings = Settings(data_dir=str(tmp_path), p2p_enabled=False, api_key=KEY,
                        tx_rate_limit_per_minute=1000, rate_limit_per_minute=10_000)
    with TestClient(create_app(settings, node=node, enable_p2p=False)) as c:
        yield c


def test_status_blocks_and_errors(client, node, helpers, alice):
    helpers.mine_blocks(node, alice.key_hash, 2)
    st = client.get("/v1/status").json()
    assert st["height"] == 2 and st["network"] == "dev" and st["peers"] == 0
    blocks = client.get("/v1/blocks?limit=2").json()
    assert [b["height"] for b in blocks] == [2, 1]
    full = client.get("/v1/blocks/height/1").json()
    assert full["transactions"][0]["kind"] == "coinbase"
    assert client.get(f"/v1/blocks/{full['hash']}").json()["hash"] == full["hash"]
    assert client.get("/v1/blocks/height/99").status_code == 404
    bad = client.get("/v1/blocks/nothex")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid-request"


def test_account_and_transaction_flow(client, node, helpers, alice, bob):
    helpers.mine_blocks(node, alice.key_hash, 1)
    acct = client.get(f"/v1/accounts/{alice.address}").json()
    assert acct["balance_formatted"] == "50.00000000" and acct["next_nonce"] == 0
    tx = alice.sign_transfer(bob.address, 1_000, DEV.min_fee, acct["next_nonce"])
    r = client.post("/v1/transactions", json={"hex": tx.to_hex()})
    assert r.status_code == 201 and r.json()["txid"] == tx.txid_hex
    assert client.get(f"/v1/transactions/{tx.txid_hex}").json()["confirmed"] is False
    assert client.get("/v1/mempool").json()["count"] == 1
    dup = client.post("/v1/transactions", json={"hex": tx.to_hex()})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "mempool-duplicate"
    helpers.mine_next(node, alice.key_hash)
    done = client.get(f"/v1/transactions/{tx.txid_hex}").json()
    assert done["confirmed"] and done["block_height"] == 2
    hist = client.get(f"/v1/accounts/{bob.address}/transactions").json()
    assert [h["txid"] for h in hist] == [tx.txid_hex]
    assert client.get("/v1/accounts/BFdeadbeef").status_code == 400


def test_malformed_transaction_rejected(client):
    assert client.post("/v1/transactions", json={"hex": "zz"}).status_code == 422
    assert client.post("/v1/transactions", json={"hex": "00"}).status_code == 400
    assert client.post("/v1/transactions", json={}).status_code == 422


def test_admin_endpoints_need_key(client, alice):
    body = {"address": alice.address}
    assert client.post("/v1/mining/start", json=body).status_code == 401
    assert client.post("/v1/mining/start", json=body, headers={"X-API-Key": "x" * 24}).status_code == 401
    ok = client.post("/v1/mining/start", json=body, headers={"X-API-Key": KEY})
    assert ok.status_code == 200 and client.get("/v1/mining").json()["mining"] is True
    assert client.post("/v1/mining/stop", headers={"X-API-Key": KEY}).json() == {"mining": False}
    assert client.post("/v1/network/connect", json={"host": "x", "port": 1},
                       headers={"X-API-Key": KEY}).status_code == 503


def test_admin_disabled_without_key(node, tmp_path, alice):
    settings = Settings(data_dir=str(tmp_path), p2p_enabled=False, api_key="")
    with TestClient(create_app(settings, node=node, enable_p2p=False)) as c:
        r = c.post("/v1/mining/start", json={"address": alice.address})
        assert r.status_code == 403 and r.json()["error"]["code"] == "admin-disabled"