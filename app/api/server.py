import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application
from telegram.error import RetryAfter
from app.config import settings
from app.interface.telegram_handler import setup_handlers
from app.database.connection import init_db
from app.graph.workflow import init_graph

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ptb_app = Application.builder().token(settings.telegram_token).build()
setup_handlers(ptb_app)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize database tables
    await init_db()

    # 2. Initialize the LangGraph with AsyncPostgresSaver (requires running event loop)
    await init_graph()

    # 3. Initialize Telegram PTB application
    await ptb_app.initialize()

    # 4. Register webhook with flood-control retry
    for attempt in range(6):
        try:
            await ptb_app.bot.set_webhook(url=settings.webhook_url.strip())
            logger.info(f"Webhook set to {settings.webhook_url.strip()}")
            break
        except RetryAfter as e:
            wait = e.retry_after + 1
            logger.warning(f"Flood control — waiting {wait}s (attempt {attempt+1}/6)...")
            await asyncio.sleep(wait)
    else:
        logger.error("Could not set webhook after 6 attempts.")

    await ptb_app.start()
    yield

    await ptb_app.bot.delete_webhook()
    await ptb_app.stop()
    await ptb_app.shutdown()


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        logger.info("--- Received Webhook ---")
        data = await request.json()
        logger.info(f"Update: {data}")
        update = Update.de_json(data, ptb_app.bot)
        logger.info(f"Processing update {update.update_id}")
        await ptb_app.process_update(update)
        logger.info(f"Done with update {update.update_id}")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/health")
async def health():
    from app.graph.workflow import app_graph
    return {
        "status": "healthy",
        "graph_ready": app_graph is not None,
    }
