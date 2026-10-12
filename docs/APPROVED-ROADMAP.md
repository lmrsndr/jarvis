# Approved Jarvis implementation programme

Approved by Elem on 13 October 2026, Europe/London.
All ten stages are authorised for implementation and testing locally. Approval does not mean tests have passed.

## Execution policy
Read AGENTS.md and docs/IMPLEMENTATION.md before changes. Inspect the actual checkout and installed tools.
Use a separate local branch codex/jarvis-local-worker; preserve all existing work and user data.
Do not delete files, reset history, change unrelated PC configuration, expose ports, or disable security controls.
Keep Jarvis runtime local-first. No paid or remote inference fallback. Development Codex uses the owner's existing sign-in.
Do not expose .env values, credentials, owner auth hashes, private footage, personal databases, or raw microphone recordings in reports.
Never invent interfaces, results, hardware observations, or finished stages.
When a stage is blocked, document the exact missing input and continue independent authorised work.
No new service accounts, purchases, emails or application write actions during tests.
Keep tests reversible. Use synthetic fixtures and separate test databases; do not modify live app data.
The staged scope is broad, but neither a fixed overnight deadline nor unattended physical audio testing is promised.

## Stage 1: Installation and diagnostics
- Start, stop, restart and update commands with process identity checks and duplicate-server prevention.
- Voice dependency preflight and independent backend/Ollama/mic/STT/TTS health.
- Diagnostic export with secret redaction.
- Preserve owner settings, memory and installed skills; document recovery.
Acceptance: actionable errors, no stale-server update failures, safe repeatable updates.

## Stage 2: Reliable listening
- Continuous capture with a dedicated local wake-word detector; check model/software licences and Windows support.
- Speech activity detection, silence timeout, recording limit, device selection and input meter.
- Push-to-talk fallback and explicit waiting/listening/transcribing/thinking states.
- Recover from disconnects and failed transcription without duplicate requests.
Acceptance: fixtures for wake, silence, command boundaries and recovery; live microphone results separately labelled.

## Stage 3: Natural local speech
- Evaluate a natural local English TTS engine, prefer British English when an appropriately licensed voice is available.
- Voice preview, saved selection/speed/volume, mute/replay/stop.
- Full long-response playback, speak prose rather than raw code/tables.
- Coordinate capture and playback to avoid self-triggering; validate rather than assume acoustic echo cancellation.
Acceptance: no truncated responses in automated playback tests; visible synthesis/playback errors; physical speaker test remains separate.

## Stage 4: Conversation controls
- Follow-up context and adjustable follow-up window.
- Distinct stop listening, stop speaking, cancel conversation request, and job cancellation semantics.
- Interruption where feasible; cancel stale recordings/responses; deduplicate requests.
- Clarify uncertain consequential commands.
Acceptance: follow-up, cancellation, interruption and stale-response tests.

## Stage 5: Personality
- Owner-editable personality: calm, practical, curious, quietly witty, concise British English.
- Calls the owner Elem, not constant sir; occasional dry humour, no theatrical chatter.
- Candour about mistakes, uncertainty, access, job state and incomplete work.
- Suggest rather than constantly interrupt; respectfully challenge impractical plans.
- Never pretend to have feelings or observations; personality cannot override permissions.
Acceptance: representative tone/honesty tests.

## Stage 6: Owner knowledge and memory
- Editable/exportable/deleteable/expirable profile and memories with provenance and confirmation status.
- Seed relevant owner facts through an explicit inspectable import; don't hardcode them into prompts.
- Owner: Elem (Elemer Sandor); Europe/London; prefers direct answers, full code and step-by-step troubleshooting.
- Prefers local processing, low running costs, reliability/accuracy before speed, UK date formatting.
- Projects: Bundlebee affiliate workflows and PostGameLens match processing/tactical analysis; Jarvis is their umbrella controller.
- Windows 11 Pro, Ryzen 9 9900X, 32 GB RAM, MSI B650 GAMING PLUS WIFI; RTX 4060 Ti 8 GB and RTX 5060 Ti 16 GB via riser.
- Intended local model Qwen3.5 9B Q4_K_M on 5060 Ti; Qwen2.5 14B Q5_K_M is an installed alternative, not an automatic switch.
- For Westhaven work use learners rather than students.
- Exclude health, family and credentials from initial profile; propose future memories for review.
Acceptance: corrections persist, latest commands override older preferences, explain preference provenance.

## Stage 7: Bundlebee
- Validate existing read-only link adapter; audit summaries, traceable recommendations, schedules/checkpoints/retries/reporting.
- Inspect actual app contracts before adding capabilities; permissions per workflow.
- Existing source repo: lmrsndr/affiliate-marketing-app. API base must be configured, not invented.
- No live publishing, price changes, affiliate clicks or writes during acceptance tests.
Acceptance: real read-only audit before write workflows.

## Stage 8: PostGameLens Studio
- Discover actual workstation job interface before integration.
- Queue/status/progress/failure/output verification, resource priority and cooperative checkpoints where supported.
- Prevent duplicates; accurately distinguish stitching/rendering/tactical capability.
- W:\PostGameLens is a previously mentioned possible install location, not proof of an available processing command.
Acceptance: representative real job/output verification when interface and safe test input exist.

## Stage 9: Unattended scheduling and reports
- London-time one-off/recurring scheduling and DST tests.
- Email configuration, report preview, progress/failure alerts and quiet hours. Do not send real emails without explicit owner test instruction.
- Restart/interrupted-job recovery, bounded retries, backup/restore.
- Explain what processes must remain running.
Acceptance: scheduled synthetic job survives restart and prepares expected report; real SMTP delivery separately pending credentials/authorisation.

## Stage 10: Verification and handover
- Backend/frontend/integration/synthetic audio tests, 4K and mobile/accessibility checks.
- Stage-by-stage implementation and test ledger.
- Full Windows commands and a short physical mic/speaker/GPU/application acceptance checklist.
- Do not call unattended operation dependable until real workflows pass.
