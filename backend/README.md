# Strategy Research and Validation Lab backend

The backend is deliberately separate from the browser-only analyzer. It stores immutable experiment configurations and chronological results in SQLite for local research, exposes FastAPI endpoints, and uses a bounded background-worker interface. PostgreSQL/TimescaleDB and an external queue can replace the local adapters without changing experiment definitions.

## Run

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/research`.

The dashboard starts with **NO COMPLETED EXPERIMENTS**. Import real completed-candle data before running a test. The API never inserts demonstration market results.
