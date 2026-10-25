# EchoResolve

A local-first, voice-enabled collections agent prototype for synthetic borrower accounts.

## Table of Contents

- [About](#about)
- [Built With](#built-with)
- [Getting Started](#getting-started)
- [Usage](#usage)
- [Evaluation](#evaluation)
- [Roadmap](#roadmap)
- [Acknowledgments](#acknowledgments)

## About

EchoResolve connects a local speech interface to a borrower workflow API backed by SQLite.

- Retrieves persisted synthetic borrower and account context.
- Creates payment proposals without immediately creating commitments.
- Requires explicit confirmation and rejects expired or replayed proposals.
- Restricts voice requests to narrowly recognized, read-only balance questions.
- Isolates automated tests from the live demo database.

### Architecture

```text
Microphone / WAV
      |
      v
Local audio model (ASR)
      |
      v
Read-only intent allowlist
      |
      v
FastAPI agent <----> SQLite
      |
      v
Response verification
      |
      v
Local audio model (TTS)
```

## Built With

- Python 3.11
- FastAPI
- SQLite
- Pytest
- LFM2.5-Audio via an OpenAI-compatible inference server

## Getting Started

### Prerequisites

- Python 3.11
- Required Python packages installed in a virtual environment
- A running LFM2.5-Audio server for voice interaction

The voice client defaults to `http://127.0.0.1:9931/v1`. This repository currently has no root dependency manifest; install the required packages in your environment before launching the services.

### Start the API

In PowerShell:

```powershell
$env:PYTHONPATH = ".\src"
.\.venv\Scripts\python.exe -m uvicorn echoresolve.api:app --host 127.0.0.1 --port 8000
```

Health check: `GET http://127.0.0.1:8000/health`

### Start the voice demo

In a second terminal:

```powershell
$env:PYTHONPATH = ".\src"
.\.venv\Scripts\python.exe .\scripts\echoresolve_voice.py
```

## Usage

Voice commands:

- `/record` — record a spoken query
- `/wav <path>` — process an existing WAV file
- `/quit` — exit

The default demo borrower is `BOR-1001`. Borrower context is available at `GET /borrowers/BOR-1001/context`.

The voice interface forwards only narrowly recognized balance questions. Other requests are rejected before reaching the agent backend.

## Evaluation

| Check | Result |
|---|---:|
| Automated test suite | 71 passed |
| Voice-intent regression tests | 18 passed |
| Named functional scenarios | 11/11 passed |
| Evaluation failures | 0 |

The 11 scenarios cover context retrieval, proposal limits, confirmation, expiry, replay protection, verification, and safe fallback.

These results demonstrate tested prototype behavior—not production reliability, real-world collections effectiveness, or regulatory compliance.

### Observed Voice Latency

A previously observed local run took approximately **5.1 seconds for transcription** and **6.3 seconds for speech generation**, producing about **4.9 seconds of audio**. These are individual observations, not controlled benchmarks or latency guarantees.

## Roadmap

- [ ] Add authentication, authorization, and borrower identity verification.
- [ ] Add structured monitoring, alerting, and operational diagnostics.
- [ ] Benchmark latency, load, and failure recovery reproducibly.
- [ ] Establish privacy, retention, encryption, and audit requirements.
- [ ] Add human escalation and review collections-specific legal requirements.
- [ ] Integrate payments only with appropriate authorization, idempotency, and reconciliation.
