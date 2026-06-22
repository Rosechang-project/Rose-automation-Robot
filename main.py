# main.py
import os
from contextlib import asynccontextmanager
from datetime import datetime

import pytz
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from linebot.v3.exceptions import InvalidSignatureError

from scheduler import setup_scheduler, smart_reminder_job
from services.line_service import get_line_handler

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.scheduler = setup_scheduler()
    app.state.scheduler.start()
    yield
    app.state.scheduler.shutdown()


app = FastAPI(lifespan=lifespan)
TZ = pytz.timezone("Asia/Taipei")
HANDLER = get_line_handler()


@app.get("/")
async def home():
    return {"status": "Rose 行程管理機器人運作中", "uptime": str(datetime.now(TZ))}


@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature")
    body = await request.body()
    try:
        HANDLER.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"


@app.post("/cron/reminder")
async def trigger_reminder(x_cron_secret: str | None = Header(default=None)):
    expected_secret = os.getenv("CRON_SECRET")
    if not expected_secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET is not configured")
    if x_cron_secret != expected_secret:
        raise HTTPException(status_code=403, detail="Invalid cron secret")

    summary = smart_reminder_job()
    return {"status": "triggered", "summary": summary, "triggered_at": str(datetime.now(TZ))}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
