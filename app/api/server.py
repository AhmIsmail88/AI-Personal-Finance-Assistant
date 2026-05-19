import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application
from telegram.error import RetryAfter
from app.config import settings
from app.interface.telegram_handler import setup_handlers
from app.database.connection import AsyncSessionLocal, init_db
from app.graph.workflow import init_graph
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ptb_app = Application.builder().token(settings.telegram_token).build()
setup_handlers(ptb_app)


async def send_payment_reminders():
    """
    Runs daily — checks fixed_payments and sends Telegram reminders
    to each user whose payment is due within their remind_days_before window.
    """
    while True:
        try:
            today = datetime.now(timezone.utc).date()
            async with AsyncSessionLocal() as session:
                query = text("""
                    SELECT user_id, name, amount, currency, due_day, remind_days_before
                    FROM fixed_payments
                    WHERE is_active = TRUE
                """)
                result = await session.execute(query)
                payments = result.fetchall()

            for row in payments:
                user_id      = row.user_id
                name         = row.name
                amount       = row.amount
                currency     = row.currency
                due_day      = row.due_day
                remind_before = row.remind_days_before

                # حساب تاريخ الاستحقاق الجاي
                try:
                    due_date = today.replace(day=due_day)
                except ValueError:
                    # يوم مش موجود في الشهر (مثلاً 31 في شهر 30 يوم)
                    import calendar
                    last_day = calendar.monthrange(today.year, today.month)[1]
                    due_date = today.replace(day=min(due_day, last_day))

                # لو عدى الموعد الشهر ده — اتحسب للشهر الجاي
                if due_date < today:
                    month = today.month % 12 + 1
                    year  = today.year + (1 if today.month == 12 else 0)
                    try:
                        due_date = due_date.replace(year=year, month=month)
                    except ValueError:
                        continue

                days_until_due = (due_date - today).days

                if 0 <= days_until_due <= remind_before:
                    if days_until_due == 0:
                        msg = f"⚠️ تذكير: {name} مستحق اليوم!\nالمبلغ: {amount} {currency}"
                    else:
                        msg = (
                            f"🔔 تذكير: {name} مستحق بعد {days_until_due} يوم "
                            f"(يوم {due_day} من الشهر)\nالمبلغ: {amount} {currency}"
                        )
                    try:
                        await ptb_app.bot.send_message(chat_id=user_id, text=msg)
                        logger.info(f"Reminder sent to {user_id} for {name}")
                    except Exception as send_err:
                        logger.warning(f"Could not send reminder to {user_id}: {send_err}")

        except Exception as e:
            logger.error(f"Reminder scheduler error: {e}", exc_info=True)

        # ينتظر 24 ساعة قبل الدورة الجاية
        await asyncio.sleep(86400)


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

    # Start daily reminder scheduler as background task
    reminder_task = asyncio.create_task(send_payment_reminders())
    logger.info("Payment reminder scheduler started.")

    yield

    reminder_task.cancel()
    try:
        await reminder_task
    except asyncio.CancelledError:
        pass

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
