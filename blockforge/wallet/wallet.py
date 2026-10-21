"""Wallet: key custody, address derivation and transaction signing.

Design rules:
  * The private key lives only inside the Wallet object and in the encrypted
    keystore file. There is deliberately no method that returns it, and the
    object cannot be pickled or repr'd with the secret.
  * Signing uses the audited primitives in core/crypto.py (ECDSA secp256k1,
    RFC6979, low-S) through Transaction.create_transfer.
  * Amounts are integer base units; text amounts go through core/amounts.py.

CLI (talks to a node's HTTP API; signing happens locally):
    python -m blockforge.wallet.wallet new      --file wallet.json
    python -m blockforge.wallet.wallet address  --file wallet.json
    python -m blockforge.wallet.wallet balance  --file wallet.json --node http://127.0.0.1:8000
    python -m blockforge.wallet.wallet send     --file wallet.json --to BF... --amount 1.5 [--fee 0.0001]
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from blockforge.consensus.params import ConsensusParams, Network, get_params
from blockforge.core import crypto
from blockforge.core.amounts import AmountError, format_amount, to_base_units
from blockforge.core.transaction import MAX_MEMO_LEN, Transaction
from blockforge.wallet import keystore


class WalletError(ValueError):
    """Raised for invalid wallet operations."""


class Wallet:
    __slots__ = ("_secret", "_params", "public_key", "key_hash", "address")

    def __init__(self, secret: bytes, params: ConsensusParams) -> None:
        self._secret = bytes(secret)
        self._params = params
        try:
            self.public_key = crypto.private_to_public(self._secret)
        except crypto.CryptoError as exc:
            raise WalletError(str(exc)) from exc
        self.key_hash = crypto.pubkey_hash(self.public_key)
        self.address = crypto.key_hash_to_address(self.key_hash, params.address_prefix)

    # ------------------------------------------------------------ construction
    @classmethod
    def generate(cls, params: ConsensusParams) -> "Wallet":
        return cls(crypto.generate_private_key(), params)

    @classmethod
    def load(cls, path: str, password: str, params: ConsensusParams) -> "Wallet":
        blob = keystore.load_keystore(path)
        wallet = cls(keystore.decrypt_key(blob, password), params)
        if blob.get("address") != wallet.address:
            raise WalletError("keystore address does not match this network or key")
        return wallet

    def save(self, path: str, password: str, scrypt_n: int = keystore.SCRYPT_N) -> None:
        blob = keystore.encrypt_key(self._secret, password, self.address,
                                    self.public_key.hex(), n=scrypt_n)
        keystore.save_keystore(path, blob)

    # ----------------------------------------------------------------- signing
    def sign_transfer(self, to_address: str, amount: int, fee: int, nonce: int,
                      memo: bytes = b"") -> Transaction:
        """Build and sign a transfer. The node enforces balance and nonce rules."""
        try:
            recipient = crypto.address_to_key_hash(to_address, self._params.address_prefix)
        except crypto.CryptoError as exc:
            raise WalletError(f"invalid recipient address: {exc}") from exc
        if amount <= 0:
            raise WalletError("amount must be positive")
        if fee < self._params.min_fee:
            raise WalletError(f"fee below network minimum ({self._params.min_fee})")
        if len(memo) > MAX_MEMO_LEN:
            raise WalletError("memo too long")
        tx = Transaction.create_transfer(self._secret, self._params, recipient,
                                         amount, fee, nonce, memo)
        tx.validate_stateless(self._params)
        return tx

    # ------------------------------------------------------------- safety nets
    def __repr__(self) -> str:
        return f"Wallet(address={self.address})"

    def __reduce__(self):  # prevents pickling the secret by accident
        raise TypeError("Wallet cannot be pickled")


# ================================================================== CLI helpers
def _http(method: str, url: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        raise WalletError(f"node returned {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise WalletError(f"cannot reach node: {exc}") from exc


def _params(name: str) -> ConsensusParams:
    return get_params(Network(name))


def _cmd_new(args: argparse.Namespace) -> None:
    params = _params(args.network)
    password = getpass.getpass("New wallet password: ")
    if password != getpass.getpass("Repeat password: "):
        raise WalletError("passwords do not match")
    wallet = Wallet.generate(params)
    wallet.save(args.file, password)
    print(f"Created {args.file}\nAddress: {wallet.address}")
    print("Back up the file AND remember the password: there is no recovery.")


def _open(args: argparse.Namespace) -> Wallet:
    return Wallet.load(args.file, getpass.getpass("Wallet password: "), _params(args.network))


def _cmd_address(args: argparse.Namespace) -> None:
    print(_open(args).address)


def _cmd_balance(args: argparse.Namespace) -> None:
    wallet = _open(args)
    acct = _http("GET", f"{args.node}/v1/accounts/{wallet.address}")
    print(f"balance:   {format_amount(acct['balance'])} BF\n"
          f"spendable: {format_amount(acct['spendable'])} BF\n"
          f"next nonce: {acct['next_nonce']}")


def _cmd_send(args: argparse.Namespace) -> None:
    params = _params(args.network)
    wallet = _open(args)
    amount = to_base_units(args.amount)
    fee = to_base_units(args.fee) if args.fee else params.min_fee
    acct = _http("GET", f"{args.node}/v1/accounts/{wallet.address}")
    tx = wallet.sign_transfer(args.to, amount, fee, acct["next_nonce"],
                              (args.memo or "").encode("utf-8"))
    result = _http("POST", f"{args.node}/v1/transactions", {"hex": tx.to_hex()})
    print(f"submitted txid {result['txid']}")


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="blockforge-wallet")
    parser.add_argument("--network", default="dev", choices=[n.value for n in Network])
    parser.add_argument("--file", default="wallet.json")
    parser.add_argument("--node", default="http://127.0.0.1:8000")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("new").set_defaults(fn=_cmd_new)
    sub.add_parser("address").set_defaults(fn=_cmd_address)
    sub.add_parser("balance").set_defaults(fn=_cmd_balance)
    send = sub.add_parser("send")
    send.add_argument("--to", required=True)
    send.add_argument("--amount", required=True, help="in BF, e.g. 1.5")
    send.add_argument("--fee", help="in BF; default = network minimum")
    send.add_argument("--memo")
    send.set_defaults(fn=_cmd_send)
    args = parser.parse_args(argv)
    try:
        args.fn(args)
    except (WalletError, keystore.KeystoreError, AmountError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())