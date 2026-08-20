# Run Guide

How to run the full AIVRA stack locally after cloning the repositories.

## Repositories

- **Backend** (this repo): `aivra-backend`
- **Frontend**: `aivra` — clone separately, as a sibling folder.

## How many terminals you need

**4 terminals must stay open** while you work, plus **1 one-time Docker command** (it runs in the background, so it does not need its own open terminal).

| # | Terminal | What it runs |
|---|----------|---------------|
| — | Docker (one-time / as needed) | Postgres, Redis, MinIO |
| 1 | Backend API | FastAPI (uvicorn) |
| 2 | Background worker | RQ job worker |
| 3 | AI voice screening agent | LiveKit voice-call agent |
| 4 | Frontend | Vite dev server |

If you don't need to test AI voice screening calls, you can skip terminal 3.

## One-time setup

**Backend:**
```powershell
cd aivra-backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
# then fill in .env: DATABASE_URL, REDIS_URL, JWT secrets, OpenAI key,
# and (only if testing voice calls) the HR_LIVEKIT_*/HR_SIP_TRUNK_ID/SMTP_* values
```

**Frontend:**
```powershell
cd aivra
npm install
# create .env.local with:
# VITE_API_URL=http://localhost:8001/api/v1
```

## Docker (Postgres, Redis, MinIO)

Run once — it starts in the background, so you don't need to keep this terminal open:
```powershell
cd aivra-backend
docker compose up -d
```

Then, the **first time only**, apply database migrations:
```powershell
.venv\Scripts\Activate.ps1
alembic upgrade head
```

## Terminal 1 — Backend API

```powershell
cd aivra-backend
.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```
Runs at `http://localhost:8001`. Restart this terminal manually after backend code changes (no auto-reload).

## Terminal 2 — Background worker

```powershell
cd aivra-backend
.venv\Scripts\Activate.ps1
python -m app.workers.worker
```
Processes resume parsing, JD matching, screening calls, and email/scheduling jobs.

## Terminal 3 — AI voice screening agent (optional)

Only needed if you're placing/testing real AI screening phone calls.
```powershell
cd aivra-backend
.venv\Scripts\Activate.ps1
python -m app.ai_employees.hr.runtime.screening_agent start
```

## Terminal 4 — Frontend

```powershell
cd aivra
npm run dev
```
Runs at `http://localhost:5173`.

## Order to start them in

1. Docker (`docker compose up -d`) — wait for containers to be healthy.
2. `alembic upgrade head` (first time / after new migrations only).
3. Terminal 1 (backend API).
4. Terminal 2 (worker).
5. Terminal 3 (screening agent) — only if needed.
6. Terminal 4 (frontend).
