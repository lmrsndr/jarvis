# Jarvis

Jarvis is a local-first modular assistant foundation. It uses FastAPI, Vue 3, SQLite, and a simple local vector index. Ollama is the default provider. OpenAI and Gemini are optional and only used when selected in the UI or request payload and when matching API keys are present in `.env`.

## Ubuntu Setup

Install system dependencies:

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip nodejs npm
```

Install and run Ollama separately, then pull a model:

```bash
ollama pull llama3.1
```

Create the environment file:

```bash
cp .env.example .env
```

Only add `OPENAI_API_KEY` or `GEMINI_API_KEY` if you want those providers available. Jarvis will not use them unless you explicitly select `openai` or `gemini`.

Set `JARVIS_ADMIN_PASSWORD_HASH` to enable protected memory deletion. The value should be a SHA-256 hash of the admin password:

```bash
python3 -c "import hashlib; print(hashlib.sha256('your-password'.encode()).hexdigest())"
```

## Backend

```bash
cd /home/s-ndrlm-r/Projects/Jarvis
python3.12 -m venv main
main/bin/python -m pip install -r jarvis/backend/requirements.txt
cd jarvis/backend
../../main/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

If you prefer a project-local venv, create it inside `jarvis/backend` and use that instead.

Health checks:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/system/health
```

## Safe Remote Access

Jarvis is local-only by default:

```env
JARVIS_LOCAL_ONLY=true
JARVIS_ALLOW_REMOTE=false
JARVIS_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
```

In this mode, non-local clients are refused. This is the safest mode for normal development.

For local LAN or private-network use, prefer binding to a private interface only after you have set `JARVIS_ADMIN_PASSWORD_HASH`:

```env
JARVIS_HOST=0.0.0.0
JARVIS_LOCAL_ONLY=false
JARVIS_ALLOW_REMOTE=true
JARVIS_ALLOWED_ORIGINS=http://your-lan-host:5173
```

Remote clients must log in with the admin password before using API routes. Local loopback access still works without a session for development.

Tailscale is the recommended remote-access path. Run Jarvis on a Tailscale-only machine or interface, keep `JARVIS_ALLOW_REMOTE=true`, and set `JARVIS_ALLOWED_ORIGINS` to the exact Tailscale frontend origin.

Cloudflare Tunnel can also work, but treat it as internet exposure. Use exact allowed origins, HTTPS, Cloudflare Access or equivalent identity controls, and keep the Jarvis admin password strong. Do not expose provider keys or `.env`.

Avoid raw router port-forwarding. Jarvis is designed for local-first and private tunnel use, not direct unauthenticated public internet exposure.

Security behavior:

- Remote access is disabled by default.
- Non-local access requires a login session when enabled.
- Admin actions still require password re-confirmation.
- Security headers and CORS are configured by the backend.
- Login failures and admin-password failures are audit logged.

## Provider Switching

Jarvis exposes three provider choices:

- `local` maps to Ollama and is the default.
- `openai` is available only when `OPENAI_API_KEY` exists in `.env`.
- `gemini` is available only when `GEMINI_API_KEY` exists in `.env`.

List provider status:

```bash
curl http://127.0.0.1:8000/api/system/providers
```

Switch provider explicitly:

```bash
curl -X POST http://127.0.0.1:8000/api/system/provider \
  -H 'Content-Type: application/json' \
  -d '{"provider":"local"}'
```

Chat with the selected provider:

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Hello Jarvis"}'
```

Or choose a provider for a single chat request:

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Hello Jarvis","provider":"local"}'
```

When `openai` or `gemini` is used, chat responses include metadata like:

```json
{
  "external_provider_used": true,
  "provider": "openai",
  "model": "gpt-4.1-mini"
}
```

API keys stay on the backend. The frontend only receives provider names and availability flags.

## Tool routing

Before sending chat prompts to Ollama, OpenAI, or Gemini, Jarvis checks enabled plugins and routes tool-dependent requests to an appropriate tool when one is available. Filesystem requests use `filesystem_manager` for trees, listings, reads, safe creates, and appends. Current or web-backed questions are routed to `web_search` when that plugin is enabled, and echo/plugin test prompts can use `echo_tool`.

Jarvis does not use memory as a substitute for tools. It will not invent filesystem state, fake command output, local file contents, logs, search results, current/live information, or project structure. If a request requires a tool and no suitable enabled plugin is available, Jarvis responds clearly instead of guessing.

Destructive filesystem actions from normal chat use a two-step confirmation flow. Delete, overwrite, and rename requests are not executed from the first request. Jarvis stores a pending protected action, returns the exact approval phrase required by `filesystem_manager`, and only executes if that phrase is sent back in the same conversation within 5 minutes. Expired or unrelated approval phrases are refused.

When a tool is used, `/api/chat` response metadata includes:

```json
{
  "tool_used": "filesystem_manager",
  "tool_action": "delete",
  "requires_confirmation": true,
  "executed": false,
  "tool_reason": "User asked to delete a file.",
  "model_used_after_tool": false
}
```

## Persistent Memory

Jarvis stores structured memory locally in SQLite and indexes it in a local hash-based vector store. It does not use OpenAI, Gemini, or any remote embedding API by default.

Supported memory types:

- `fact`
- `project`
- `task`
- `script`
- `log`
- `search_result`
- `conversation_summary`
- `system_change`

Create memory:

```bash
curl -X POST http://127.0.0.1:8000/api/memory \
  -H 'Content-Type: application/json' \
  -d '{
    "memory_type": "fact",
    "title": "Local-first rule",
    "content": "Jarvis should prefer local providers and local storage.",
    "tags": ["local", "policy"],
    "source": "manual",
    "confidence": 1.0
  }'
```

List memory:

```bash
curl http://127.0.0.1:8000/api/memory
```

Search memory:

```bash
curl "http://127.0.0.1:8000/api/memory/search?q=local-first"
```

Fetch one memory:

```bash
curl http://127.0.0.1:8000/api/memory/1
```

Delete memory with admin confirmation:

```bash
curl -X DELETE http://127.0.0.1:8000/api/memory/1 \
  -H 'Content-Type: application/json' \
  -d '{"admin_password":"your-password"}'
```

During chat, Jarvis first decides whether local memory is needed. It does not search or inject memory for general knowledge questions that can be answered without stored context.

Jarvis uses memory only when the request is user-specific, project-specific, about the local Jarvis setup/files, asks to remember/recall/continue/resume prior work, or otherwise needs stored context for correctness. When memory is used, Jarvis injects only strong matches, limits recall to the top 3 memories by default, and filters by relevant memory type. Identity facts such as the user's name are excluded unless the current request naturally needs identity or personalization.

The chat prompt includes this memory policy:

> You have access to local memory, but you must not mention or use stored memories unless they are directly relevant to the user's current request. First decide whether the question can be answered from general knowledge alone. Use memory only when it improves correctness or continuity. Do not say 'I remember' unless the user asks about memory. Do not include personal facts unless naturally needed.

After useful exchanges, Jarvis still saves a local `conversation_summary` for future continuity.

## Voice Input

Voice is only another input method. The browser records microphone audio, sends it to `POST /api/voice/transcribe`, then the transcribed text is sent through the same chat pipeline as typed messages.

Default speech-to-text is local-only:

```env
JARVIS_STT_PROVIDER=local
JARVIS_STT_MODEL=base
```

Install optional local STT support:

```bash
cd /home/s-ndrlm-r/Projects/Jarvis
main/bin/python -m pip install faster-whisper
```

The first local transcription may download the selected Whisper model. Use a smaller model such as `tiny` or `base` for lower local CPU usage:

```env
JARVIS_STT_MODEL=base
```

Microphone recording requires a browser context that allows `navigator.mediaDevices.getUserMedia`, such as `http://127.0.0.1:5173`. OpenAI and Gemini transcription are not used by default.

Direct transcription endpoint:

```bash
curl -X POST http://127.0.0.1:8000/api/voice/transcribe \
  -F "file=@voice.webm"
```

Text-to-speech is currently a placeholder in `backend/voice/tts.py`; no TTS provider is enabled yet.

## Plugins

Plugins are modular Python tools loaded from `backend/plugins/tools`. A plugin package is a `.zip` containing a folder or root files like:

```text
echo_tool/
  tool.py
  tool.schema.json
  README.md
  tests/test_tool.py
```

Each `tool.py` must expose:

```python
PLUGIN_NAME = "echo_tool"
PLUGIN_DESCRIPTION = "Return supplied text unchanged."
PLUGIN_VERSION = "0.1.0"
PLUGIN_PERMISSIONS = "safe"

def run(args: dict) -> dict:
    return {"text": args.get("text", "")}
```

List plugins:

```bash
curl http://127.0.0.1:8000/api/plugins
```

View metadata:

```bash
curl http://127.0.0.1:8000/api/plugins/echo_tool
```

Run a safe plugin:

```bash
curl -X POST http://127.0.0.1:8000/api/plugins/echo_tool/run \
  -H 'Content-Type: application/json' \
  -d '{"args":{"text":"hello"}}'
```

Plugin permissions:

- `safe` plugins run normally.
- `medium` plugins require `"confirmed": true`.
- `dangerous` plugins require `admin_password`.

Every plugin run is written to the audit log.

## Safe Plugin Installer

Jarvis can install new plugins, but the installer is schema-driven and non-destructive. It is intended for adding folders under `backend/plugins/tools`, then enabling the plugin in `backend/plugins/registry.json` only after validation and tests pass.

Installer safety rules:

- No file deletion is supported.
- Existing files are not overwritten unless an admin password is supplied and the exact approval phrase is included.
- Protected core paths require admin password and an exact approval phrase, and files must include marker blocks.
- If plugin tests fail, the install is rolled back and the failed files are moved into `storage/backups/plugins`.
- Registry updates happen only after tests pass.
- All installer steps are audit logged.

Protected core paths:

```text
backend/core
backend/api
backend/memory
frontend/src
backend/main.py
```

Preview an install package by sending base64 zip content:

```bash
curl -X POST http://127.0.0.1:8000/api/plugins/install/preview \
  -H 'Content-Type: application/json' \
  -d '{"filename":"my_tool.zip","package_base64":"..."}'
```

Apply a package:

```bash
curl -X POST http://127.0.0.1:8000/api/plugins/install/apply \
  -H 'Content-Type: application/json' \
  -d '{
    "filename": "my_tool.zip",
    "package_base64": "...",
    "admin_password": null,
    "approval_text": ""
  }'
```

Approval phrase formats:

```text
APPROVE CORE CHANGE: filename.py
APPROVE OVERWRITE: filepath
APPROVE DELETE: filepath
```

Deletion approval is intentionally refused in this version.

## Frontend

In a second terminal:

```bash
cd /home/s-ndrlm-r/Projects/Jarvis/jarvis/frontend
npm install
npm run dev
```

Open the Vite URL shown in the terminal, usually `http://127.0.0.1:5173`.

For local development, proxy API requests through Vite or run the backend on the same origin behind your own reverse proxy. The backend already allows local Vite origins through CORS.

## Tests

```bash
cd /home/s-ndrlm-r/Projects/Jarvis/jarvis/backend
../../main/bin/python -m pytest
```

## Provider Rules

- `local` / `ollama` is the default provider.
- `openai` is disabled unless `OPENAI_API_KEY` is set.
- `gemini` is disabled unless `GEMINI_API_KEY` is set.
- Cloud providers are never selected automatically; use `POST /api/system/provider` or pass a provider in the chat request.
- External-provider responses include explicit metadata showing that a remote provider was used.
- Remote HTTP access is blocked by default unless `JARVIS_ALLOW_REMOTE=true`.
- Memory is local-first: SQLite plus the local vector index under `JARVIS_VECTOR_PATH`.
- Voice transcription is local-first and uses `faster-whisper` only when installed.

## Project Layout

```text
backend/   FastAPI app, providers, memory, plugins, tests
frontend/  Vue 3 + Vite app
storage/   local uploads, logs, memory files, backups
```
