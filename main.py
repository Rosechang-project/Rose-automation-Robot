# main.py
from contextlib import asynccontextmanager
from datetime import datetime

import pytz
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from linebot.v3.exceptions import InvalidSignatureError

from scheduler import setup_scheduler
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
