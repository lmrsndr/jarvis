from __future__ import annotations
import asyncio
import csv
import io
import time
import psutil
import httpx


async def snapshot(settings):
    gpus = []
    try:
        p = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=index,name,uuid,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(p.communicate(), 3)
        except BaseException:
            p.kill()
            await p.wait()
            raise
        for r in csv.reader(io.StringIO(out.decode())):
            if len(r) != 8:
                continue

            def number(v):
                try:
                    return float(v.strip())
                except ValueError:
                    return None

            gpus.append(
                dict(
                    index=int(r[0]),
                    name=r[1].strip(),
                    uuid=r[2].strip(),
                    utilization=number(r[3]),
                    used_mib=number(r[4]),
                    total_mib=number(r[5]),
                    temperature=number(r[6]),
                    watts=number(r[7]),
                )
            )
    except (OSError, asyncio.TimeoutError):
        pass
    ollama = {"online": False, "models": []}
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
            r = await client.get(settings.ollama_base_url + "/api/ps")
            r.raise_for_status()
            ollama = {"online": True, "models": r.json().get("models", [])}
    except (httpx.HTTPError, ValueError):
        pass
    ram = psutil.virtual_memory()
    return {
        "at": time.time(),
        "cpu_percent": psutil.cpu_percent(),
        "ram_percent": ram.percent,
        "ram_used_gib": round(ram.used / 2**30, 1),
        "ram_total_gib": round(ram.total / 2**30, 1),
        "gpus": gpus,
        "ollama": ollama,
    }
