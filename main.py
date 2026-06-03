# main.py
import os
import pytz
from contextlib import asynccontextmanager  # 🔑 工具統一排好在頂端
from fastapi import FastAPI, Request, HTTPException
from linebot.v3.exceptions import InvalidSignatureError
from dotenv import load_dotenv
from datetime import datetime

# 🔑 完美召喚兩大核心組件：獨立排程引擎 與 LINE分析總指揮
from scheduler import setup_scheduler
from services.line_service import get_line_handler

load_dotenv()

# --- ⏰ 啟動與關閉的生命週期總管 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # [Startup]: 伺服器啟動時，把排程鬧鐘上鍊
    app.state.scheduler = setup_scheduler()
    app.state.scheduler.start()
    yield
    # [Shutdown]: 伺服器關閉時，優雅地關掉鬧鐘
    app.state.scheduler.shutdown()

# 核心主角：宣告 app 時，直接把生命週期管理掛進去（只宣告這一次！）
app = FastAPI(lifespan=lifespan)

TZ = pytz.timezone('Asia/Taipei')

# 向 LINE 部門牽線，拿到訊息接收的最高指揮官
HANDLER = get_line_handler()


# --- 🏢 1. FastAPI 網頁網路櫃檯 (對外接口) ---
@app.get("/")
async def home():
    return {"status": "小精靈二號機運作中", "uptime": str(datetime.now(TZ))}

@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get('X-Line-Signature')
    body = await request.body()
    try:
        # 櫃檯接起電話，確認密鑰無誤後，直接轉接給後台的 LINE 總指揮官，自己不分析任何一個字！
        HANDLER.handle(body.decode('utf-8'), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return 'OK'

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)