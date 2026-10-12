from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
import httpx
from control.skills import execute_skill
from control.store import now
from control.mail import send_pending


class Scheduler:
    def __init__(self, store, settings):
        self.store = store
        self.settings = settings
        self.task = None
        self.worker = None
        self.active = None
        self.closed = False
        self.agent_lock = asyncio.Lock()

    async def start(self):
        self.task = asyncio.create_task(self.loop())

    async def close(self):
        self.closed = True
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def loop(self):
        while not self.closed:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.store.event(
                    "error", "Scheduler iteration failed; inspect configuration."
                )
            await asyncio.sleep(2)

    async def tick(self):
        # Reports are scheduled independently of job completion and the LLM.
        for job in self.store.jobs():
            if job["report_at"] and job["report_at"] <= now():
                self.store.outbox(
                    "Jarvis progress: " + job["title"],
                    f"Job {job['id']}\nStatus: {job['status']}\nResult: {job['result']}\nError: {job['error']}",
                )
                self.store.update_job(job["id"], report_at=None)
                self.store.event(
                    "report", "Scheduled progress report prepared: " + job["title"]
                )
        await asyncio.to_thread(send_pending, self.store)
        if self.store.setting("paused", False) or self.active:
            return
        if self.agent_lock.locked():
            return
        job = self.store.claim()
        if not job:
            return
        self.active = job
        self.worker = asyncio.create_task(self.execute(job))

    async def execute(self, job):
        manifest = next(
            (s for s in self.store.skills() if s["id"] == job["skill"]), None
        )
        try:
            if not manifest:
                raise ValueError("Skill is not installed")
            if "llm_gpu" in manifest.get(
                "resources", []
            ) or "video_gpu" in manifest.get("resources", []):
                async with (
                    self.agent_lock,
                    httpx.AsyncClient(trust_env=False, timeout=20) as client,
                ):
                    r = await client.post(
                        self.settings.ollama_base_url + "/api/generate",
                        json={"model": self.settings.ollama_model, "keep_alive": 0},
                    )
                    r.raise_for_status()
            self.store.event("job", "Started " + job["title"], {"job_id": job["id"]})
            result = await execute_skill(manifest, job["args"], job)
            paused = result.get("paused") is True
            self.store.update_job(
                job["id"],
                status="paused" if paused else "completed",
                result=result,
                checkpoint=result.get("checkpoint", {}),
                error="",
            )
            self.store.event(
                "job",
                ("Checkpoint saved: " if paused else "Completed: ") + job["title"],
            )
            if not paused and job["interval_seconds"]:
                next_at = (
                    datetime.now(timezone.utc)
                    + timedelta(seconds=job["interval_seconds"])
                ).isoformat()
                self.store.enqueue(
                    job["title"],
                    job["skill"],
                    job["args"],
                    job["priority"],
                    next_at,
                    interval_seconds=job["interval_seconds"],
                    approved=True,
                    max_attempts=job["max_attempts"],
                )
            if not paused and self.store.setting("presence", "home") == "away":
                self.store.outbox("Jarvis completed: " + job["title"], str(result))
        except asyncio.CancelledError:
            self.store.update_job(
                job["id"],
                status="interrupted",
                error="Execution interrupted. Review before resuming.",
            )
            raise
        except Exception as exc:
            # Unknown transport failures may have applied side effects. Retry only an owner-declared idempotent skill.
            retry = (
                manifest
                and manifest.get("idempotent")
                and job["attempts"] < job["max_attempts"]
            )
            self.store.update_job(
                job["id"],
                status="queued" if retry else "failed",
                error=str(exc)[:500],
                run_at=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
            )
            self.store.event("error", "Job failed: " + job["title"])
            if self.store.setting("presence", "home") == "away":
                self.store.outbox(
                    "Jarvis needs attention: " + job["title"],
                    "Execution failed. Review the dashboard before retrying.",
                )
        finally:
            self.active = None
