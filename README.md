# Finance Tracker

> Import credit card statement CSVs into a Google Sheets budget, with transactions auto-categorized by Claude.

Finance Tracker is a small full-stack app for people who already keep a budget in Google Sheets and want to stop hand-typing every transaction. Upload an Elan Financial Services CSV, review the proposed categories and naming in a preview UI, and commit approved rows to the spreadsheet.

---

## Features

- **CSV import** — parses Elan Financial Services credit card statements.
- **AI categorization** — Anthropic's Claude classifies each transaction against the budget's existing category list (fetched live from the sheet) and learns merchant naming conventions from the current year's prior entries.
- **Preview → commit** — two-stage flow. The preview endpoint runs CSV parsing, dedup, refund pairing, and Claude classification; nothing is written until you POST the (optionally edited) preview to the commit endpoint.
- **Duplicate detection** — checks `(date, amount)` against existing rows in each month's Expense section before insertion. Duplicates are collapsed by default in the UI.
- **Refund pairing** — same-CSV `DEBIT` + `CREDIT` rows with matching amount, similar merchant, and within ±14 days are paired and skipped automatically. Unmatched credits that match an already-imported sheet row surface as a warning.
- **CSV persistence across sign-in** — uploaded file survives the OAuth redirect via `sessionStorage`, so you don't have to re-pick the file after signing in.
- **Google sign-in (UX only)** — frontend OAuth identifies the user for display; backend Sheets I/O always uses a service account.

## Architecture

```
┌──────────────┐      ┌────────────────────────┐      ┌──────────────────┐
│ React + Vite │──────│ FastAPI (Vercel Python │──────│ Google Sheets API│
│  (src/)      │      │  Serverless Functions) │      │  Anthropic API   │
│              │      │  (api/)                │      └──────────────────┘
└──────────────┘      └────────────────────────┘
```

- **Frontend** — React 19 + TypeScript, built with Vite.
- **Backend** — FastAPI app in `api/index.py`, deployed as a Vercel Python function. `vercel.json` rewrites `/api/*` to it.
- **Storage** — a single Google Sheets spreadsheet is the source of truth (no database). One tab per year (`2025`, `2026`, …); months are 4-column blocks laid out horizontally.
- **Auth model** — Sheets reads/writes use a **service account** (`credentials.json` locally, `GOOGLE_SERVICE_ACCOUNT_JSON` env var in production). User Google sign-in is independent and powers the frontend identity display only.

### Repo layout

```
api/                    FastAPI backend (Vercel Python serverless)
  index.py              Routes: auth, /import/preview, /import/commit
  utils/
    helper.py           CSV parsing, Sheets client (service account), date/amount helpers
    categorize_transactions.py   Claude category inference, historical name learning
    import_transactions.py       Preview/commit orchestration, refund pairing
src/                    React frontend
  App.tsx               Upload, preview table, refund display, commit
  AuthContext.tsx       Google OAuth state for frontend identity
  TopBar.tsx
vercel.json             Routes /api/* to api/index.py
requirements.txt        Python deps (FastAPI, google-api-python-client, anthropic)
package.json            Frontend deps + scripts
```

---

## Getting started

### Prerequisites

- **Node.js** ≥ 20 and npm
- **Python** ≥ 3.11
- A **Google Cloud project** with the Sheets API enabled
- A **Google service account** for that project, with its JSON key downloaded to `./credentials.json`
- An **Anthropic API key**
- A Google Sheets spreadsheet matching the expected budget layout (per-year tabs, 4-column month blocks; see `SPREADSHEET_ID` in `api/utils/import_transactions.py`). **Share the sheet with the service account's email** as an Editor.
- (Optional, only for the frontend sign-in UI) OAuth 2.0 web client credentials

### 1. Clone and install

```bash
git clone https://github.com/<your-fork>/finance-tracker.git
cd finance-tracker

npm install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment variables

Create a `.env` file in the project root:

```bash
ENV=development
BACKEND_URL=http://localhost:8000
FRONTEND_URL=http://localhost:5173

# Optional: only needed if you want the frontend "Sign in with Google" button
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...

ANTHROPIC_API_KEY=sk-ant-...
```

| Variable | Required | Notes |
|---|---|---|
| `ENV` | yes | `development` or `production`. Toggles CORS allow-list and a few log lines. |
| `BACKEND_URL` | yes | Used to build the OAuth callback URL for the frontend sign-in flow. |
| `FRONTEND_URL` | yes | Used for CORS and OAuth redirects. |
| `ANTHROPIC_API_KEY` | yes | Used by `categorize_transactions.py`. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | no | Only required if you want the optional frontend sign-in button. Sheets I/O does not use these. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | prod | Raw JSON of the service-account key (for Vercel). Locally `credentials.json` at the project root is used instead. |

### 3. Run the dev servers

Two processes — run each in its own terminal.

**Frontend (Vite):**

```bash
npm run dev
# → http://localhost:5173
```

**Backend (FastAPI via uvicorn):**

```bash
source .venv/bin/activate
uvicorn api.index:app --reload --port 8000
# → http://localhost:8000/api
```

> The frontend expects the backend at `/api/*`. Either configure a Vite dev proxy (`server.proxy` in `vite.config.ts`) or set `VITE_API_BASE=http://localhost:8000` so fetches resolve to the right origin.

### 4. Use it

1. Open http://localhost:5173
2. Upload an Elan CSV statement (file persists across sign-in if you sign in after uploading)
3. Review the categorized preview — edit expense names, change categories, skip rows, un-pair refunds
4. Click **Commit N rows to sheet** to write approved rows

---

## Scripts

### Frontend

| Command | Description |
|---|---|
| `npm run dev` | Start the Vite dev server with HMR. |
| `npm run build` | Type-check and produce a production build in `dist/`. |
| `npm run preview` | Preview the production build locally. |
| `npm run lint` | Run ESLint over the project. |

### Backend

| Command | Description |
|---|---|
| `uvicorn api.index:app --reload --port 8000` | Run FastAPI locally with autoreload. |
| `pip install -r requirements.txt` | Install Python dependencies. |
| `python -m api.utils.import_transactions <csv_path>` | CLI: preview + auto-commit a CSV without the UI. |

---

## API

All routes are mounted under `/api`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Liveness probe. |
| `GET` | `/api/auth/google` | Begin Google OAuth flow (frontend identity only). |
| `GET` | `/api/auth/callback` | OAuth redirect target; bounces back to the frontend with tokens. |
| `GET` | `/api/auth/status` | Reports `{"method": "service_account"}` — Sheets I/O is always service-account. |
| `POST` | `/api/import/preview` | Multipart upload of a CSV; returns `{previews, refunds_paired}` with classified rows per month and any auto-paired refunds. |
| `POST` | `/api/import/commit` | Accepts the (optionally edited) preview JSON and writes approved rows to the sheet. No LLM call at this stage. |

---

## Deployment

The app deploys to **Vercel** as a single project. `vercel.json` routes `/api/*` to the Python function in `api/index.py`; everything else is served from the Vite build.

```bash
vercel deploy        # preview
vercel deploy --prod # production
```

In the Vercel project settings, set the env vars from the table above. For Sheets access, set `GOOGLE_SERVICE_ACCOUNT_JSON` to the **entire contents** of `credentials.json` on one line — the backend will parse it at runtime. Do **not** commit `credentials.json` or `.env`.

---

## License

See [LICENSE](LICENSE).
