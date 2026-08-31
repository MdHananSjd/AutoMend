# AutoMend Target Service

Minimal production-ready target service for Cloud Run failure testing.
Features fully deterministic, debug-gated failure injection scenarios for the AutoMend self-healing pipeline.

## Running Locally

### Option 1: Python Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
DEBUG_MODE=true PORT=8000 uvicorn app.main:app --host 0.0.0.0 --port 8000
```
