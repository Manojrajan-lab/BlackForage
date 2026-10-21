# BlockForge

BlockForge is a Python-based Proof-of-Work cryptocurrency node with a FastAPI HTTP API and a React + TypeScript web frontend. It includes blockchain data structures, transaction handling, mining, persistent chain state, and peer-to-peer networking.

> **Status:** Development project. Do not use with real funds or expose it to the public internet as a production cryptocurrency without independent security review, consensus testing, operational hardening, and a reviewed release process.

## Features

- Proof-of-Work consensus, block validation, and mining support
- Blocks, transactions, Merkle trees, cryptographic utilities, and address handling
- SQLite-backed chain state and development network data
- FastAPI endpoints for chain status, blocks, accounts, transactions, and node operations
- Peer-to-peer networking with configurable seed peers
- API request limits, optional API-key protection for administrative endpoints, and configurable CORS
- React, TypeScript, and Vite frontend
- Pytest test suite

## Technology stack

- **Backend:** Python 3.11+, FastAPI, Pydantic, Uvicorn
- **Storage:** SQLite
- **Cryptography:** coincurve and cryptography
- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS
- **Tests:** pytest, pytest-asyncio, httpx

## Project structure

```text
BlackForage/
├── blockforge/
│   ├── api/          # HTTP API, schemas, security, error handling
│   ├── consensus/    # Proof-of-Work, rewards, difficulty, validation
│   ├── core/         # Blocks, transactions, cryptography, Merkle trees
│   ├── mempool/      # Pending transaction pool
│   ├── network/      # Peer-to-peer networking
│   ├── node/         # Node lifecycle and chain/fork handling
│   ├── storage/      # Persistent chain state
│   └── wallet/       # Wallet utilities and CLI
├── frontend/         # React + TypeScript web app
├── tests/            # Backend tests
├── data/             # Local development data
├── pyproject.toml
└── requirements.txt
```

## Requirements

- Python 3.11 or newer
- Node.js and npm
- Git

## Run the backend (Windows PowerShell)

Run these commands from the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn --factory blockforge.api.app:create_app --host 127.0.0.1 --port 8000
```

If `.env.example` is not present in your checkout, skip the `Copy-Item` command and configure settings with environment variables as needed.

The API will be available at `http://127.0.0.1:8000`. Interactive API documentation is available at `http://127.0.0.1:8000/docs`, and the health endpoint is `http://127.0.0.1:8000/health`.

### Run the backend tests

```powershell
python -m pytest -q
```

## Run the frontend

Open a second terminal and run:

```powershell
cd frontend
npm ci
npm run dev
```

Vite prints the local frontend URL when the development server starts.

Useful frontend commands:

```powershell
npm run build
npm run typecheck
npm run lint
npm test
```

## Configuration

Backend settings use the `BLOCKFORGE_` environment-variable prefix and can also be loaded from a `.env` file. Common settings include:

| Variable | Purpose |
|---|---|
| `BLOCKFORGE_NETWORK` | Network configuration (defaults to `dev`) |
| `BLOCKFORGE_DATA_DIR` | Directory for local database and peer data |
| `BLOCKFORGE_API_HOST` | API bind host |
| `BLOCKFORGE_API_PORT` | API port (defaults to `8000`) |
| `BLOCKFORGE_API_KEY` | Enables protection for administrative endpoints when configured; use a strong key |
| `BLOCKFORGE_CORS_ORIGINS` | Comma-separated allowed frontend origins |
| `BLOCKFORGE_P2P_ENABLED` | Enables/disables peer-to-peer networking |
| `BLOCKFORGE_P2P_PORT` | Peer-to-peer port (defaults to `9333`) |
| `BLOCKFORGE_SEEDS` | Comma-separated seed peers in `host:port` format |
| `BLOCKFORGE_MINE` | Enables mining at node startup |
| `BLOCKFORGE_MINER_ADDRESS` | Address to receive mining rewards when mining is enabled |
| `BLOCKFORGE_LOG_LEVEL` | Logging level |

Review `blockforge/config.py` and `blockforge/consensus/params.py` for the authoritative settings and consensus parameters. Never commit secrets or private keys.

## API overview

The API includes endpoints for node health and status, block lookup/listing, transaction submission, and administrative operations. The exact request and response schemas are documented in the running API docs at `/docs`.

## Security notes

- Keep the API bound to localhost during development.
- Do not expose administrative endpoints without configuring and reviewing API-key protection.
- Configure CORS to allow only trusted frontend origins.
- Use a separate development data directory and network while testing.
- Do not commit `.env`, wallet secrets, private keys, local databases, or other sensitive files.
- A passing test suite does not by itself establish production readiness or economic/security safety.

## Contributing

1. Create a branch for your change.
2. Add or update tests.
3. Run `python -m pytest -q` and relevant frontend checks.
4. Open a pull request describing the change and its tests.

## License

No license has been specified yet. Unless a license is added to this repository, the default copyright rules apply and reuse or redistribution may be restricted.
