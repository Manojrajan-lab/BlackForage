import json
import os
import pickle
import pytest
from blockforge.consensus.params import DEV, MAINNET
from blockforge.wallet import keystore
from blockforge.wallet.wallet import Wallet, WalletError

N = keystore.MIN_SCRYPT_N
def test_save_load_roundtrip_and_permissions(tmp_path):
    w = Wallet.generate(DEV)
    path = str(tmp_path / "w.json")
    w.save(path, "correct horse", scrypt_n=N)
    if os.name == "posix":
        assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    loaded = Wallet.load(path, "correct horse", DEV)
    assert loaded.address == w.address
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    assert w._secret.hex() not in raw

def test_wrong_password_and_tamper(tmp_path):
    w = Wallet.generate(DEV)
    path = str(tmp_path / "w.json")
    w.save(path, "correct horse", scrypt_n=N)
    with pytest.raises(keystore.KeystoreError):
        Wallet.load(path, "wrong password", DEV)
    with open(path, "r", encoding="utf-8") as f:
        blob = json.load(f)
    blob["address"] = Wallet.generate(DEV).address
    with open(path, "w", encoding="utf-8") as f:
        json.dump(blob, f)
    with pytest.raises(keystore.KeystoreError):
        Wallet.load(path, "correct horse", DEV)

def test_refuses_overwrite_weak_password_and_bad_kdf(tmp_path):
    w = Wallet.generate(DEV)
    path = str(tmp_path / "w.json")
    w.save(path, "correct horse", scrypt_n=N)
    with pytest.raises(keystore.KeystoreError):
        w.save(path, "correct horse", scrypt_n=N)
    with pytest.raises(keystore.KeystoreError):
        w.save(str(tmp_path / "x.json"), "short", scrypt_n=N)
    with open(path, "r", encoding="utf-8") as f:
        blob = json.load(f)
    blob["kdf"]["n"] = 2**30
    with pytest.raises(keystore.KeystoreError):
        keystore.decrypt_key(blob, "correct horse")


def test_same_key_gives_same_address_on_every_network(tmp_path):
    w = Wallet.generate(DEV)
    path = str(tmp_path / "w.json")
    w.save(path, "correct horse", scrypt_n=N)
    loaded = Wallet.load(path, "correct horse", MAINNET)
    assert loaded.address == w.address

def test_secret_never_leaks():
    w = Wallet.generate(DEV)
    assert w._secret.hex() not in repr(w)
    with pytest.raises(TypeError):
        pickle.dumps(w)
    with pytest.raises(WalletError):
        w.sign_transfer("BFnotanaddress", 1, DEV.min_fee, 0)