# AGENTS.md

Rules for future Codex work in this repository:

- Keep Jarvis local-first. Ollama and local storage are the default path.
- Do not use OpenAI, Gemini, or any remote API automatically. Remote providers require explicit user selection and configured keys.
- Do not make destructive edits. Never delete files, reset history, or discard work without explicit instruction.
- Do not delete user files or generated data unless the user directly asks for that exact deletion.
- Protect core files under `backend/core`, `backend/memory`, and provider selection logic. Read them carefully before changing behavior.
- Prefer plugin-based changes for new tools, integrations, and capabilities.
- Keep provider implementations isolated behind `core/providers.py`.
- Keep memory behavior explicit and inspectable. Avoid hidden background uploads or remote sync.
- Include tests where practical for every behavior change.
- Keep changes scoped. Do not refactor unrelated modules while implementing a feature.
- Never commit secrets. Do not print or log API keys from `.env`.
