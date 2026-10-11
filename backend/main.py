from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from api.chat_routes import router as chat_router
from api.memory_routes import router as memory_router
from api.plugin_routes import router as plugin_router
from api.system_routes import router as system_router
from api.voice_routes import router as voice_router
from core.config import get_settings
from core.permissions import ensure_local_request
from memory.db import MemoryDatabase
import asyncio
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from control.store import Store
from control.scheduler import Scheduler
from control.routes import router as control_router


settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    memory = MemoryDatabase(settings.memory_db_path)
    memory.init()
    store = Store(settings.memory_db_path)
    store.init()
    _app.state.control_memory = memory
    _app.state.control_store = store
    _app.state.agent_lock = asyncio.Lock()
    scheduler = Scheduler(store, settings)
    scheduler.agent_lock = _app.state.agent_lock
    _app.state.scheduler = scheduler
    await scheduler.start()
    try:
        yield
    finally:
        await scheduler.close()


app = FastAPI(title="Jarvis", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(self)"
    response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
    return response


async def local_guard(request: Request) -> None:
    ensure_local_request(request, get_settings())


@app.get("/health")
def root_health():
    return {"status": "ok", "app": "jarvis"}


app.include_router(system_router, dependencies=[Depends(local_guard)])
app.include_router(chat_router, dependencies=[Depends(local_guard)])
app.include_router(memory_router, dependencies=[Depends(local_guard)])
app.include_router(plugin_router, dependencies=[Depends(local_guard)])
app.include_router(voice_router, dependencies=[Depends(local_guard)])

app.include_router(control_router, dependencies=[Depends(local_guard)])
frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="command-center")
