# Jarvis command center

This branch adds a native-tool local agent and a durable control plane. The original chat/plugin API remains for compatibility; the TV UI uses `/api/control/chat` exclusively. Qwen3.5 9B Q4_K_M is the default. Qwen2.5 remains an explicitly selectable configuration alternative, not an automatic paid or remote fallback.

## Windows install

1. Install Python 3.12, Node.js LTS, Git and Ollama. Download `qwen3.5:9b-q4_K_M` with `ollama pull`.
2. Check out this branch: `git clone --branch codex/jarvis-command-center https://github.com/lmrsndr/jarvis.git`.
3. From the repository, run `powershell -ExecutionPolicy Bypass -File .\scripts\Install-Jarvis.ps1`. Add `-Voice` for local faster-whisper transcription. Whisper downloads its model on first use.
4. Setup creates `.env` with a PBKDF2 owner password hash. Existing settings are preserved: if upgrading, explicitly set `OLLAMA_MODEL=qwen3.5:9b-q4_K_M` in `.env` if it still names the old model. Never commit `.env`.
5. Quit an already running Ollama tray app if you want the launcher to apply the dedicated GPU settings. Run `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-Jarvis.ps1`, visit http://127.0.0.1:8000 and sign in under Control room → Owner. The app binds to localhost.
6. Use TV mode for fullscreen. A directly attached TV is a monitor; a separate TV browser cannot reach localhost. For a separate device, deliberately configure Tailscale, a TLS reverse proxy, `JARVIS_LOCAL_ONLY=false`, `JARVIS_ALLOW_REMOTE=true`, and matching origins. Authentication remains required. No network exposure is set up automatically.
7. Optionally run `scripts\Enable-Autostart.ps1` to start after Windows sign-in. The machine must be awake for schedules; Windows sleep is not overridden. Disable the task using Task Scheduler if needed.

## Skills and adapters

A read-only Bundlebee catalogue auditor is shipped in `backend/adapters/bundlebee.py`, matched to the real application's `/api/products` contract. Set `BUNDLEBEE_API_BASE` to your API URL including `/api`, then load its template in Control room → Skills and explicitly install it. It inspects published products and non-redirecting product HEAD responses, never calls affiliate click tracking, and never edits the catalogue. Redirects/bot blocks are review findings, not a claim that a product is broken. Prices and affiliate attribution remain unverified. Publishing and price updates still need a separately authorised adapter.

No pretend Studio backend is shipped. `docs/skill-examples.json` contains **example contracts, not existing service endpoints**. The complete schema is [skill-schema.json](skill-schema.json). Install one manifest at a time only after implementing or configuring the matching adapter in the relevant project. The skill network shows disconnected until installation. Tokens live in named environment variables, never in manifest content.

An HTTP adapter receives `{job_id, request_id, args, checkpoint}` and the `Idempotency-Key` header. A command adapter receives the same JSON on stdin, with no shell expansion, and must emit one JSON result on stdout. HTTP endpoints use HTTPS except loopback. Redirects are not followed. A result must satisfy the skill's `success_schema` and contain `ok: true`. Returning only an accepted/queued response is insufficient; the adapter must wait for the workflow and validate its outputs. Cancellation after an HTTP timeout cannot be assumed to cancel remote work.

A checkpoint-capable adapter may return `{paused:true, checkpoint:{...}}`. Jarvis persists the checkpoint for an explicitly requested resume. Running jobs cannot be arbitrarily paused by the host; adapters must cooperate at boundaries. Queue pause prevents new starts. A failed non-idempotent job without a checkpoint cannot be resumed automatically. On restart, running jobs become interrupted for review. Only declared idempotent skills retry, using the same request ID.

Skill installation is owner-authenticated. `risk: approval` requires approval for every new job; `risk: automatic` is an explicit owner-installed standing policy, including recurrence. Command skills are trusted code running as the Windows user: process separation and timeouts are **not an OS sandbox**. Do not install code you would not run yourself. Legacy Python ZIP packages are confined to their own plugin folder and cannot modify core/frontend files.

## Jobs, dates and memory

The scheduler runs without the LLM. Jobs, approval states, checkpoints, preference feedback, questions and outbox reports persist in SQLite. Priorities use lower numbers first. Execution is deliberately serial for this initial version. Recurrence is a fixed delay after successful completion; recurring calendar rules are not implemented. Reporting uses a separate timestamp and is checked while execution runs. Missed due reports are prepared on the next awake tick.

Relative weekdays use a calendar tool with Europe/London and timezone-aware dates. DST nonexistent times are rejected. Ambiguous autumn clock-change times use fold=0; confirm unusual overnight schedules manually. Current messages override stored preferences through the agent prompt; permission enforcement remains application code. Preferences are explicit and editable, can expire, and require owner sign-in to save. Proposed model preferences become review questions. Existing legacy memories remain available through memory search; the old hash-vector index is not claimed to be semantic retrieval. Owner text-document ingestion is available at `/api/control/knowledge`; semantic embeddings and preference deletion are future work.

GPU telemetry comes from nvidia-smi, CPU/RAM from psutil. Missing measurements show unavailable. GPU-requiring jobs unload the configured model before execution; chat is refused while that job reserves the GPU. This is admission control and model unloading, not automatic GPU reassignment or VRAM pooling. Skills must choose their device inside their own adapters. Unconfigured skills do not appear in the model tool registry.

## Voice, presence and email

Push-to-record transcribes locally on CPU with cached faster-whisper models; Windows temporary audio files are closed before decoding and erased afterward. Speech synthesis selects a browser voice marked local; if none exists, replies remain text. The animated face shows actual interface state, not consciousness or an audio amplitude measurement. Wake mode is an experimental opt-in six-second transcription loop in the browser, not a dedicated low-power wake-word engine. It works only while the page is active and has microphone permission. Browser/device microphone support varies. Transcription chunks may miss split commands; voice cannot install skills or bypass approvals.

Presence is an explicit Home/Away control, not surveillance-based proximity detection. Configure `JARVIS_SMTP_*`, `JARVIS_EMAIL_FROM` and `JARVIS_EMAIL_TO` in `.env` to send reports using STARTTLS. Mail is sent only to that configured owner address. Optional `JARVIS_EMAIL_QUIET_START`/`JARVIS_EMAIL_QUIET_END` (HH:mm in Europe/London) defer all outbound delivery during quiet hours. Reports remain in the outbox if not configured. Delivery retries are bounded; SMTP interruption can duplicate mail. Incoming-email commands, inbound sender verification are not implemented; emails cannot execute commands.

## Backup, operation and validation

Control room → Back up database uses SQLite's online backup. It includes the control plane and legacy memory, but not `.env`, plugin source or external project artifacts. Keep a separate protected copy of those. To restore, stop Jarvis, copy the current database aside and restore a selected backup to the configured database path. Never restore while the application is running.

Run `python -m pytest -c backend/pytest.ini backend` with `PYTHONPATH=backend`, and `npm ci && npm run build` in frontend. CI runs the Python tests on Windows and Linux and builds the frontend. GPU/model/voice/SMTP/external-adapter integration must additionally be validated on the owner PC. No live Windows/GPU test is implied by container checks.

## Remaining product work

Write-capable Bundlebee operations and the real Studio execution adapter require their actual authentication and pipeline contracts. Also remaining: granular per-action standing permissions, resumable live progress streaming, native wake-word engine, inbound authenticated email commands, semantic knowledge ingestion, model-specific thinking policies and full signing/release installer. These are not presented as working capabilities in the UI. The control-center architecture supplies extension points without silently enabling them.

## Validation recorded for this branch

- 85 Python tests passed in the Linux development environment.
- Frontend production build passed.
- Browser checked at 3840×2160 and 390×844; no horizontal overflow or JavaScript page errors.
- Owner sign-in and preference creation exercised through the browser against the running backend.
- Real command-worker completion, recurrence, approval, deduplication, restart interruption, safe retry policy, password migration and package confinement are covered by tests.
- Actual Ollama/native-model operation on Windows, microphone/TTS, GPU handover, SMTP delivery and project adapters still require workstation acceptance checks.
