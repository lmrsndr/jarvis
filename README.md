# Jarvis

Jarvis is a local-first, modular AI assistant platform built with FastAPI (backend), Vue 3 (frontend), SQLite (storage), and a lightweight local vector index. Ollama is the default LLM provider, with optional support for OpenAI and Gemini when configured.

---

## ⚠️ Security Notice

Jarvis is designed for **local-first and private-network use**.

* Do **not** expose Jarvis directly to the public internet
* Use localhost, LAN, or a secure tunnel (e.g. Tailscale)
* Never commit `.env`, API keys, databases, logs, or uploaded files
* Treat plugin installation and execution as **trusted-code only**

---

## 🧰 Requirements

* Python 3.12
* Node.js + npm
* Ollama (for local LLM)

Install system dependencies:

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip nodejs npm
```

Install Ollama and pull a model:

```bash
ollama pull llama3.1
```

---

## ⚙️ Setup

Clone the repository and create your environment file:

```bash
cp .env.example .env
```

Only add API keys if you plan to use cloud providers:

* `OPENAI_API_KEY`
* `GEMINI_API_KEY`

Jarvis will not use them unless explicitly selected.

Optional: enable protected admin actions by setting:

```bash
python3 -c "import hashlib; print(hashlib.sha256('your-password'.encode()).hexdigest())"
```

Add the result to `.env` as:

```env
JARVIS_ADMIN_PASSWORD_HASH=<hash>
```

---

## 🖥 Backend

Create and install the Python environment:

```bash
cd /path/to/Jarvis
python3.12 -m venv main
main/bin/python -m pip install -r jarvis/backend/requirements.txt
```

Run the backend:

```bash
cd jarvis/backend
../../main/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Health checks:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/system/health
```

---

## 🌐 Frontend

```bash
cd /path/to/Jarvis/jarvis/frontend
npm install
npm run dev
```

Open the URL shown (usually `http://127.0.0.1:5173`).

---

## 🔐 Safe Remote Access

Default (recommended):

```env
JARVIS_LOCAL_ONLY=true
JARVIS_ALLOW_REMOTE=false
```

For LAN or private network use:

```env
JARVIS_HOST=0.0.0.0
JARVIS_LOCAL_ONLY=false
JARVIS_ALLOW_REMOTE=true
JARVIS_ALLOWED_ORIGINS=http://your-host:5173
```

Recommended remote access:

* Tailscale (preferred)
* Secure tunnel with authentication (e.g. Cloudflare Access)

Avoid direct port forwarding.

---

## 🤖 Providers

Jarvis supports:

* `local` → Ollama (default)
* `openai` → requires API key
* `gemini` → requires API key

List providers:

```bash
curl http://127.0.0.1:8000/api/system/providers
```

Switch provider:

```bash
curl -X POST http://127.0.0.1:8000/api/system/provider \
  -H 'Content-Type: application/json' \
  -d '{"provider":"local"}'
```

---

## 🧠 Chat API

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Hello Jarvis"}'
```

---

## 🔌 Plugins

Plugins live in:

```text
backend/plugins/tools/
```

Each plugin includes:

```text
tool.py
tool.schema.json
README.md
```

Example:

```python
def run(args: dict) -> dict:
    return {"text": args.get("text", "")}
```

List plugins:

```bash
curl http://127.0.0.1:8000/api/plugins
```

---

## 🧱 Plugin System Overview

Jarvis uses a modular plugin architecture with:

* Schema-driven validation
* Permission-based execution
* Audit logging
* Safe install/rollback

Plugins are categorised by permission level:

* `safe`
* `medium` (requires confirmation)
* `dangerous` (requires admin password)

---

## 🧠 Memory

Jarvis stores local memory in SQLite and a local vector index.

Supported types:

* facts
* tasks
* projects
* logs
* scripts

Create memory:

```bash
curl -X POST http://127.0.0.1:8000/api/memory \
  -H 'Content-Type: application/json' \
  -d '{"memory_type":"fact","title":"Example","content":"Test"}'
```

---

## 🎙 Voice (Optional)

Local speech-to-text:

```bash
pip install faster-whisper
```

Default:

```env
JARVIS_STT_PROVIDER=local
JARVIS_STT_MODEL=base
```

---

## 🧪 Tests

```bash
cd /path/to/Jarvis/jarvis/backend
../../main/bin/python -m pytest
```

---

## 📁 Project Structure

```text
backend/   FastAPI backend
frontend/  Vue 3 frontend
storage/   local runtime data (ignored by git)
```

---

## 🧠 Design Philosophy

* Local-first by default
* Explicit tool usage (no hidden automation)
* No hallucinated system state
* Safe-by-design plugin execution
* Extensible architecture

---

## 📌 Notes

* Jarvis will not fabricate filesystem data, logs, or external results
* Tool execution is explicit and logged
* Sensitive operations require confirmation
* External providers are opt-in only

---

## 🚧 Status

Jarvis is an evolving platform. The current focus is:

* Plugin architecture standardisation
* Trusted-source web retrieval
* Safe execution model
* Local-first AI workflows
