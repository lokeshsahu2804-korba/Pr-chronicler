# Automated Open-Source PR Chronicler and Learning Dispatcher

A production-ready FastAPI-based developer tool designed to monitor merged pull requests across open-source repositories, hydrate technical context from GitHub REST APIs, analyze architectural code changes using Google Generative AI (Gemini) orchestrated through LangChain Expression Language (LCEL), extract high-impact programming insights, and dispatch learning digests to students via SMTP email.

---

## 🏗️ Architecture

```mermaid
flowchart TD
    A[GitHub Pull Request Event] -->|Webhook POST /webhook/github| B(FastAPI Webhook Ingestion)
    B -->|Check action == 'closed' & merged == true| C{Event Filter}
    C -->|Ignored: opened, synchronize, unmerged| D[Return HTTP 200 + Log Ignore Reason]
    C -->|Accepted: Merged PR| E[GitHub REST API Hydration Client]
    E -->|GET /pulls/{number}| F[PR Title, Author, Body]
    E -->|GET /pulls/{number}/files| G[Changed Files, Patches, Diff Count]
    E -->|GET /issues/{number}| H[Linked Issues #95, #96]
    F & G & H --> I[HydratedPRContext]
    I --> J[LangChain LCEL Pipeline: Prompt | Gemini Flash | JsonOutputParser]
    J --> K[Pydantic PRReflection Validation: 3-4 Learnings]
    K --> L[SMTP Email Dispatcher: smtplib & EmailMessage]
    L --> M[Student Inbox / Delivery Log]
```

### Complete Pipeline Flow:
1. **GitHub Webhook Ingestion**: Receives `pull_request` event JSON payload with optional `X-Hub-Signature-256` HMAC-SHA256 signature verification and `X-GitHub-Delivery` in-memory idempotency.
2. **Event Filtering**: Accepts **only** when `action == "closed"` AND `pull_request.merged == true`. All other events (opened, synchronize, reopened, closed unmerged) return HTTP 200 with an explicit ignore reason and trigger **no** downstream calls.
3. **GitHub API Context Hydration**: Concurrently retrieves PR metadata, paginates through all changed files, extracts unidiff patches, calculates total diff character count, and detects linked issues (`Fixes #...`, `Closes #...`, `Resolves #...`).
4. **LangChain LCEL Synthesis**: Compiles hydrated context and diff excerpts into a structured prompt, invokes Gemini Flash via `ChatGoogleGenerativeAI` (`temperature=0.1`), and extracts structured JSON via `JsonOutputParser`.
5. **Pydantic Validation**: Validates the extracted JSON into a strict `PRReflection` schema enforcing `issue_details`, `execution_summary`, and strictly 3 to 4 `key_learnings`.
6. **SMTP Email Dispatch**: Constructs a multipart HTML portfolio email and plain-text fallback using Python standard library `smtplib` and `email.message.EmailMessage`, transmitting via an asynchronous worker thread (`asyncio.to_thread`).
7. **Lifecycle Logging**: Records end-to-end processing metrics including exact diff character counts, LLM parsed JSON, validation status, SMTP transmission results, and latency in seconds.

---

## 📂 Project Structure

```text
pr-chronicler/
├── app/
│   ├── __init__.py           # Package versioning (v0.1.0)
│   ├── main.py               # FastAPI entry point, lifespan, webhook endpoint, HMAC & idempotency
│   ├── config.py             # Pydantic Settings loading environment variables from .env
│   ├── models.py             # Pydantic schemas (PRReflection, HydratedPRContext, WebhookResponse)
│   ├── github_client.py      # Async GitHub REST client using httpx.AsyncClient with pagination
│   ├── llm_chain.py          # LangChain LCEL chain (PromptTemplate | Gemini Flash | JsonOutputParser)
│   ├── email_dispatcher.py   # Standard-library SMTP dispatcher (smtplib & EmailMessage)
│   └── logging_config.py     # Dual-channel logging (terminal stdout + pr_chronicler.log)
├── simulate_merge.py         # Complete simulation and test suite with CLI modes
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variables template
├── .env                      # Local environment configuration (git-ignored)
├── .gitignore                # Git ignore rules for logs, secrets, and caches
└── README.md                 # Project documentation
```

---

## ⚙️ Setup & Prerequisites

### 1. Requirements
- Python 3.10+ (Tested on Python 3.14)
- `pip`

### 2. Virtual Environment Setup
From inside `pr-chronicler/`:
```bash
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux
# .\venv\Scripts\activate # On Windows
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## 🔐 Environment Variables

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

| Variable | Description | Default / Example | Required |
| :--- | :--- | :--- | :--- |
| `APP_ENV` | Application environment (`development` / `production`) | `development` | Yes |
| `APP_HOST` | Host binding for Uvicorn | `127.0.0.1` | Yes |
| `APP_PORT` | Port binding for Uvicorn | `8000` | Yes |
| `LOG_LEVEL` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` | Yes |
| `LOG_FILE` | Log file destination | `pr_chronicler.log` | Yes |
| `GITHUB_TOKEN` | GitHub Personal Access Token (avoids 60 req/hr rate limits) | `ghp_...` | Optional |
| `GITHUB_WEBHOOK_SECRET` | Secret for verifying `X-Hub-Signature-256` HMAC signatures | `your_webhook_secret` | Optional |
| `GOOGLE_API_KEY` | Google Gemini API key from AI Studio | `AIzaSy...` | For Live LLM |
| `GEMINI_MODEL` | Gemini model name | `gemini-2.5-flash` | Yes |
| `SMTP_HOST` | Outgoing SMTP server host | `smtp.gmail.com` | Yes |
| `SMTP_PORT` | Outgoing SMTP server port | `587` | Yes |
| `SMTP_EMAIL` | Sender email address | `your_email@gmail.com` | Yes |
| `SMTP_APP_PASSWORD` | 16-character Google App Password (2FA required) | `abcdefghijklmnop` | Yes |
| `SMTP_USE_TLS` | Enable STARTTLS encryption | `true` | Yes |
| `SMTP_DRY_RUN` | Run dispatcher safely in dry-run mode (no live emails sent) | `true` | Yes |
| `DISPATCH_RECIPIENTS` | Comma-separated subscriber emails | `student@example.edu` | Optional |

> [!CAUTION]
> **Security Reminder**: Never commit `.env` or hardcode API keys, GitHub tokens, or SMTP passwords into any repository file.

---

## 🚀 Running the Server

Start the development server with live reload:
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Verify operational readiness via the health check endpoint:
```bash
curl -s http://127.0.0.1:8000/health
# Output: {"status":"ok"}
```

Access interactive documentation:
- Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- ReDoc: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

---

## 🧪 Testing & Simulation Suite

The project includes an end-to-end test and demonstration script ([`simulate_merge.py`](file:///Users/lokeshkumarsahu/Desktop/GEN-AI/22-october/pr-chronicler/simulate_merge.py)):

### 1. Full Demonstration & Integration Suite
Runs schema validation, email dispatcher unit testing, and all 7 webhook pipeline scenarios:
```bash
python3 simulate_merge.py
```

### 2. Dedicated SMTP Email Dispatcher Test
Verifies message construction, recipient, exact subject format, HTML layout, 3–4 key learnings, and dry-run delivery:
```bash
python3 simulate_merge.py --email
```

### 3. Independent LangChain LCEL Chain Test
Tests the standalone LCEL prompt-to-Pydantic pipeline against hydrated context:
```bash
python3 simulate_merge.py --chain
```

### 4. Pydantic Schema Rejection Test
Verifies strict enforcement of the 3–4 key learnings constraint (rejects 2 items, rejects 5 items, accepts 3 and 4):
```bash
python3 simulate_merge.py --schema
```

---

## 📋 Test Scenarios & Results

| # | Scenario | Payload Details | Expected Behavior | Verification Status |
| :-: | :--- | :--- | :--- | :-: |
| 1 | **Merged PR with Linked Issues** | `encode/httpx #103`, `action="closed"`, `merged=true` | Hydrated (8 files, 15,049 chars diff, issues #95 & #96), Synthesized, Dispatched | **PASS** |
| 2 | **Merged PR without Linked Issues** | `encode/httpx #100`, `action="closed"`, `merged=true` | Hydrated (2 files, 1,307 chars diff), Synthesized, Dispatched | **PASS** |
| 3 | **Closed Unmerged PR** | `action="closed"`, `merged=false` | HTTP 200, Ignored: `"pull request was closed but not merged"` | **PASS** |
| 4 | **Opened PR** | `action="opened"`, `merged=false` | HTTP 200, Ignored: `"action is not closed"` | **PASS** |
| 5 | **Synchronize PR** | `action="synchronize"`, `merged=false` | HTTP 200, Ignored: `"action is not closed"` | **PASS** |
| 6 | **Reopened PR** | `action="reopened"`, `merged=false` | HTTP 200, Ignored: `"action is not closed"` | **PASS** |
| 7 | **Duplicate Delivery** | Duplicate `X-GitHub-Delivery` header | HTTP 200, Ignored: `"Duplicate delivery ... already processed"` | **PASS** |

---

## 📊 Example Outputs

### 1. Structured `PRReflection` JSON
```json
{
  "issue_details": "Premature connection closes during chunked response streaming caused unhandled ConnectionResetError in the asyncio stream reader, resulting in hung client tasks.",
  "execution_summary": "Refactored stream handler by isolating request body transmission and response stream consumption into explicit lifecycle states with dedicated connection close handlers.",
  "key_learnings": [
    "Decoupling protocol transmit and receive lifecycles prevents half-closed socket descriptor leaks.",
    "Handling ConnectionResetError explicitly at transport boundaries ensures clean pool reclamation.",
    "Designing state machines for protocol transitions dramatically increases client resilience."
  ]
}
```

### 2. Representative Lifecycle Logs (`pr_chronicler.log`)
```text
2026-10-22 12:54:57 [INFO] pr_chronicler: Webhook received
Action: closed
Repository: encode/httpx
PR: #103
Title: Handle early connection closes
Author: lovelydinosaur
Merged: true
2026-10-22 12:54:57 [INFO] pr_chronicler: Event accepted: merged PR
2026-10-22 12:54:57 [INFO] pr_chronicler: GitHub API request: GET https://api.github.com/repos/encode/httpx/pulls/103 -> HTTP 200
2026-10-22 12:54:57 [INFO] pr_chronicler: GitHub API request: GET https://api.github.com/repos/encode/httpx/pulls/103/files -> HTTP 200
2026-10-22 12:54:57 [INFO] pr_chronicler: GitHub PR diff character count: 15049
2026-10-22 12:54:57 [INFO] pr_chronicler: Detected 2 linked issue reference(s) in PR body: [95, 96]
2026-10-22 12:54:58 [INFO] pr_chronicler: GitHub API request: GET https://api.github.com/repos/encode/httpx/issues/95 -> HTTP 200
2026-10-22 12:54:58 [INFO] pr_chronicler: GitHub API request: GET https://api.github.com/repos/encode/httpx/issues/96 -> HTTP 200
2026-10-22 12:54:58 [INFO] pr_chronicler: Hydration complete for encode/httpx #103: 8 changed files, 15049 diff characters, linked issue found: True
2026-10-22 12:54:58 [INFO] pr_chronicler: LLM synthesis started for encode/httpx #103
2026-10-22 12:54:58 [INFO] pr_chronicler: Raw parsed JSON output: {"issue_details": "...", "execution_summary": "...", "key_learnings": ["...", "...", "..."]}
2026-10-22 12:54:58 [INFO] pr_chronicler: Validation succeeded: PRReflection schema verified (key_learnings count: 3)
2026-10-22 12:54:58 [INFO] pr_chronicler: SMTP transmission (dry-run mode) verified for encode/httpx #103 -> Subject: '[OS-Log] PR Merged: encode/httpx (#103)' | Recipient: student@example.edu
2026-10-22 12:54:58 [INFO] pr_chronicler: SMTP transmission successful for encode/httpx #103
2026-10-22 12:54:58 [INFO] pr_chronicler: Processing completed for encode/httpx #103 in 1.77 seconds
```

### 3. Email Dispatch Format

- **Subject**: `[OS-Log] PR Merged: encode/httpx (#103)`
- **HTML Layout**:
  - **Header Card**: Blue `#0969da` banner displaying repository name and pull request number badge.
  - **Issue Details Section**: Left-bordered callout box showing root cause.
  - **Execution Summary Section**: Green left-bordered callout box showing implementation summary.
  - **Key Learnings Section**: Numbered ordered list displaying all 3–4 takeaways.
  - **Footer**: Transmission metadata and timestamp.
- **Plain-Text Alternative**: Automatically embedded multipart text fallback.

---

## 🌐 Connecting Live GitHub Webhooks (ngrok)

To receive real webhook deliveries from GitHub:

1. **Start the local server**:
   ```bash
   uvicorn app.main:app --port 8000
   ```

2. **Expose port 8000 via ngrok**:
   ```bash
   ngrok http 8000
   ```

3. **Configure the Webhook in GitHub Repository Settings**:
   - Go to: `Repository Settings` > `Webhooks` > `Add webhook`.
   - **Payload URL**: `https://<your-ngrok-subdomain>.ngrok-free.app/webhook/github`
   - **Content type**: `application/json`
   - **Secret**: Set your `GITHUB_WEBHOOK_SECRET` matching your `.env`
   - **Which events would you like to trigger this webhook?**: Select **"Let me select individual events"** and check **"Pull requests"**.
   - Save the webhook.

---

## ⏱️ Performance & Latency Validation

The project tracks actual end-to-end processing latency for merged PRs:
- **Observed Latency (Full Hydration & Processing)**:
  - `encode/httpx #103` (8 files, 15,049 diff characters, 2 linked issues): **1.77 seconds**
  - `encode/httpx #100` (2 files, 1,307 diff characters, 0 linked issues): **1.11 seconds**
- **Target Comparison**: Well within the 15-second benchmark target specified in the project requirements.
