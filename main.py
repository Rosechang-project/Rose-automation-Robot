# main.py
import os
from contextlib import asynccontextmanager
from datetime import datetime
from secrets import compare_digest

import pytz
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from linebot.v3.exceptions import InvalidSignatureError

from scheduler import setup_scheduler, smart_reminder_job
from services.line_service import get_line_handler

load_dotenv()


def internal_scheduler_enabled():
    return os.getenv("ENABLE_INTERNAL_SCHEDULER", "false").lower() in {"1", "true", "yes", "on"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.scheduler = None
    if internal_scheduler_enabled():
        app.state.scheduler = setup_scheduler()
        app.state.scheduler.start()
    try:
        yield
    finally:
        if app.state.scheduler:
            app.state.scheduler.shutdown()


app = FastAPI(lifespan=lifespan)
TZ = pytz.timezone("Asia/Taipei")
HANDLER = get_line_handler()


@app.get("/")
async def home():
    return {"status": "Rose scheduler bot is running", "uptime": str(datetime.now(TZ))}


@app.get("/cron/status")
async def cron_status(request: Request):
    scheduler = getattr(request.app.state, "scheduler", None)
    jobs = scheduler.get_jobs() if scheduler else []
    reminder_job = jobs[0] if jobs else None
    return {
        "status": "ok",
        "cron_secret_configured": bool(os.getenv("CRON_SECRET")),
        "internal_scheduler_enabled": internal_scheduler_enabled(),
        "scheduler_running": bool(scheduler and scheduler.running),
        "next_internal_reminder": str(reminder_job.next_run_time) if reminder_job else None,
        "checked_at": str(datetime.now(TZ)),
    }


@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature")
    body = await request.body()
    try:
        await run_in_threadpool(HANDLER.handle, body.decode("utf-8"), signature)
    except (InvalidSignatureError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"


def verify_cron_secret(x_cron_secret: str | None):
    expected_secret = os.getenv("CRON_SECRET")
    if not expected_secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET is not configured")
    if not x_cron_secret or not compare_digest(x_cron_secret.encode(), expected_secret.encode()):
        raise HTTPException(status_code=403, detail="Invalid cron secret")


async def run_reminder(x_cron_secret: str | None):
    verify_cron_secret(x_cron_secret)
    summary = await run_in_threadpool(smart_reminder_job)
    if summary["errors"]:
        status = "partial_failure" if summary["sent"] else "failed"
        status_code = 503
    else:
        status = "skipped" if summary.get("reason") else "completed"
        status_code = 200
    return JSONResponse(
        status_code=status_code,
        content={"status": status, "summary": summary, "triggered_at": datetime.now(TZ).isoformat()},
    )


@app.get("/cron/reminder")
async def trigger_reminder_get(x_cron_secret: str | None = Header(default=None)):
    return await run_reminder(x_cron_secret)


@app.post("/cron/reminder")
async def trigger_reminder_post(x_cron_secret: str | None = Header(default=None)):
    return await run_reminder(x_cron_secret)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
