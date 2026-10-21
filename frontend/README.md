# BlockForge Frontend

React + TypeScript + Vite dashboard for a **real** BlockForge node (`BlackForage.zip`, FastAPI backend). It shows only data the node returns. There are no mock fallbacks anywhere in `src/`.

## Run (Windows PowerShell)

Backend (from the unzipped `BlackForage` folder, Python 3.11+):

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m blockforge.wallet.wallet new --file wallet.json      # prints your BF... address
$env:BLOCKFORGE_NETWORK = "dev"
$env:BLOCKFORGE_API_KEY = "choose-a-long-random-key"           # 16+ chars; enables admin routes
$env:BLOCKFORGE_CORS_ORIGINS = "http://localhost:5173"         # REQUIRED or the browser blocks every call
$env:BLOCKFORGE_MINE = "true"; $env:BLOCKFORGE_MINER_ADDRESS = "<your BF address>"   # optional
python -m uvicorn --factory blockforge.api.app:create_app --host 127.0.0.1 --port 8000
```

Frontend (Node 20+):

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev          # http://localhost:5173
```

Scripts: `npm run typecheck`, `npm run lint`, `npm test`, `npm run build`.

Live integration test (needs a running dev node mining to the throwaway address in `tests/fixtures/python-backend.json`):

```powershell
$env:BLOCKFORGE_LIVE_URL = "http://127.0.0.1:8000"; $env:BLOCKFORGE_LIVE_ADMIN_KEY = "<node api key>"
npx vitest run tests/live
```

## Configuration (`.env`, non-secret only)

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | Node URL (also editable in Settings) |
| `VITE_NETWORK` | `dev` | Must equal the node's `BLOCKFORGE_NETWORK`; signing is disabled on mismatch |
| `VITE_REQUEST_TIMEOUT_MS` | `10000` | Per-request timeout |
| `VITE_POLL_INTERVAL_MS` | `5000` | Polling interval |

The admin API key is typed into Settings and kept in memory only. Never put it in `.env` (`VITE_*` is bundled into public JS).

## API integration map (from `blockforge/api/routes.py`)

| UI | Endpoint | Notes |
|---|---|---|
| Dashboard, header | `GET /v1/status` | height, tip, chainwork (string), mempool, supply, mining, peers |
| Explorer | `GET /v1/blocks?limit&before` | limit 1-100; `before` = exclusive height cursor |
| Block page | `GET /v1/blocks/height/{h}`, `/v1/blocks/{hash}` | full block incl. transactions |
| Tx page, search | `GET /v1/transactions/{txid}` | works for mempool and confirmed |
| Pending list | `GET /v1/mempool?limit` | limit 1-100 |
| Wallet, address | `GET /v1/accounts/{addr}`, `/transactions?limit&before` | confirmed history only |
| Send | `POST /v1/transactions {hex}` | signed in the browser; 201 `{txid}`; 409 duplicate/stale nonce |
| Network | `GET /v1/network/peers`, `POST /v1/network/connect` (admin) | |
| Mining | `GET /v1/mining`, `POST /v1/mining/start`, `/stop` (admin) | |
| Settings | `GET /health` | connectivity test |

Errors are `{"error": {"code", "message"}}`; validation failures are HTTP 422. Admin routes need `X-API-Key` (403 `admin-disabled` if the node has no key, 401 if wrong).

## Wallet and security design

- Transactions are built and signed client-side (ECDSA secp256k1, RFC6979, low-S) with `@noble/curves`. A test proves the bytes and txid equal the Python backend's for the same inputs.
- Keystores use the backend's format (scrypt → AES-256-GCM). Keys are decrypted in the browser, held in a memory-only ref, zeroed on lock, and never written to localStorage, sessionStorage, URLs or logs. Only the theme and node URL are persisted.
- The backend has no seed phrases (raw 32-byte keys). There is no recovery: back up the keystore file and remember the password.
- This is a software wallet in a web page. A compromised browser, extension or XSS can use an unlocked key. It is not hardware-backed, and nothing here claims otherwise.
- Client-side validation is a convenience. The node is the authority.

## Backend limitations and required changes

1. **CORS is off by default.** Set `BLOCKFORGE_CORS_ORIGINS`. Allowed methods/headers are already sufficient.
2. **Large integers.** Amounts are JSON numbers; mainnet max supply (1.05e16 base units) exceeds JavaScript's exact range (9.007e15). The UI displays the backend's `*_formatted` strings and skips its local balance check for unsafe values, but the API should return u64 values as strings.
3. **Consensus params are not exposed** (only `network` and `chain_id`). `src/utils/chain.ts` copies min fee, maturity and prefix from `params.py`; add `GET /v1/params`.
4. **No difficulty, hashrate, block reward or template fields.** Difficulty is derived from each block's `bits`. The Mining page says so instead of inventing numbers.
5. **No global transaction index.** The Transactions page reads mempool + the last 10 blocks; older transactions need search by txid.
6. **Address history is confirmed-only and height-paginated.** `before` is block-height based, so the UI uses `lastHeight + 1` and de-duplicates; more than 25 transactions of one address inside a single block would stall paging.
7. **P2P:** no disconnect/ban endpoint; `connect` returns `dialing` without outcome; "P2P disabled" and "0 peers" look the same on `GET /v1/network/peers`.
8. **No user auth; admin key is a static header secret** with no TLS by default; rate limiting is per client IP (all users behind a proxy share one bucket). Put the node behind HTTPS and a trusted proxy before exposing it.

## Not verified / remaining production blockers

- No browser end-to-end tests (no Playwright browsers available in the build environment). Responsive layout, real-browser keyboard navigation and visual contrast were **not** tested; the code uses semantic HTML, labels, focus rings, a skip link and native `<dialog>`, but this needs a manual pass.
- Only the `dev` network was exercised live. Testnet/mainnet values in `chain.ts` are copied, not run.
- No Content-Security-Policy / security headers are set by the Vite dev server; configure them at your static host.
- The wallet has no idle auto-lock, no hardware-wallet support, and no fee estimation (the node offers none).
