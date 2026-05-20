import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from langgraph.errors import GraphInterrupt
from langgraph.types import Command
import app.graph.workflow as workflow_module
from app.config import settings
from app.agents.excel_exporter import export_excel_report

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Handling /start command")
    await update.message.reply_text(
        "مرحباً! 👋 أنا مساعدك المالي الشخصي.\n\n"
        "أستطيع مساعدتك في:\n"
        "• 📝 تسجيل مصاريفك\n"
        "• 📊 عرض إحصائيات إنفاقك\n"
        "• 🗑️ حذف أو تعديل مصروف\n"
        "• 📁 تصدير تقرير Excel\n\n"
        "جرب: 'صرفت 50 جنيه على الأكل'"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Handling message: {update.message.text}")
    text = update.message.text
    user_id = update.effective_user.id

    app_graph = workflow_module.app_graph
    if app_graph is None:
        await update.message.reply_text("البوت لسه بيشتغل، جرب تاني بعد ثانية. 🔄")
        return

    config = {"configurable": {"thread_id": str(user_id)}}

    # ── Restore persisted conversation state from the checkpointer ──────────
    persisted = await app_graph.aget_state(config)
    prev_values = persisted.values if persisted else {}

    # Sliding window — keep last 20 messages only to control LLM context size
    history = prev_values.get("conversation_history", [])
    history = history[-20:]

    # Inject the current UTC time so date_resolver can work correctly
    current_date = datetime.now(timezone.utc).isoformat()

    initial_state = {
        # Carry forward persistent state …
        **prev_values,
        # … but always refresh per-turn fields.
        "user_message": text,
        "telegram_id": user_id,
        "thread_id": str(user_id),
        "current_date": current_date,
        # Reset transient fields so stale values don't bleed through.
        "intent": None,
        "extracted_data": None,
        "split_expenses": None,
        "update_data": None,
        "query_key": None,
        "query_params": None,
        "sql_result": None,
        "needs_clarification": False,
        "clarification_question": None,
        "pending_confirmation": False,
        "confirmation_action": None,
        "operation_status": None,
        "response": None,
        "error": None,
        # Use the windowed history (not prev_values directly to enforce the limit)
        "conversation_history": history,
    }

    try:
        # Bug #3 fix: catch GraphInterrupt to display Yes/No keyboard
        result = await app_graph.ainvoke(initial_state, config=config)

        # ── Export report — send Excel file ──────────────────────────────────
        if result.get("intent") == "export_report" and result.get("sql_result"):
            await update.message.reply_text("جاري تجهيز التقرير... ⏳")

            raw = result["sql_result"]

            # Normalize: db_agent returns dict {"expenses":[], "income":[]}
            # but guard against old list format just in case
            if isinstance(raw, dict):
                excel_data = raw
            else:
                # Fallback: treat as expenses-only list
                excel_data = {"expenses": raw, "income": []}

            success = await export_excel_report(
                sql_result=excel_data,
                bot=context.bot,
                chat_id=user_id,
                current_date=current_date,
            )
            if not success:
                await update.message.reply_text("حصل خطأ أثناء توليد التقرير. حاول تاني. 🙏")
            return

        # ── Normal response ───────────────────────────────────────────────────
        if result.get("needs_clarification") and not result.get("response"):
            await update.message.reply_text(result["clarification_question"])
        elif result.get("response"):
            await update.message.reply_text(result["response"])
        else:
            await update.message.reply_text("مش متأكد إزاي أساعدك في ده.")

    except GraphInterrupt:
        # Bug #3 fix: graph was interrupted at confirm_delete — show inline keyboard
        keyboard = [[
            InlineKeyboardButton("✅ نعم، احذف", callback_data="delete_confirm"),
            InlineKeyboardButton("❌ لأ، احتفظ", callback_data="delete_cancel"),
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚠️ هل أنت متأكد من حذف آخر مصروف؟",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Error in handle_message: {e}", exc_info=True)
        await update.message.reply_text("حصل خطأ غير متوقع. حاول تاني. 🙏")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    app_graph = workflow_module.app_graph
    if app_graph is None:
        await query.edit_message_text("البوت لسه بيشتغل، جرب تاني. 🔄")
        return

    config = {"configurable": {"thread_id": str(user_id)}}

    if query.data == "delete_confirm":
        try:
            # Resume graph with confirmation (True = delete confirmed)
            result = await app_graph.ainvoke(Command(resume=True), config=config)
            await query.edit_message_text(
                result.get("response", "✅ تم الحذف بنجاح!")
            )
        except Exception as e:
            logger.error(f"Delete confirm error: {e}", exc_info=True)
            await query.edit_message_text("حصل خطأ أثناء الحذف. حاول تاني. 🙏")
    else:
        try:
            # Resume graph with cancellation (False = keep the expense)
            await app_graph.ainvoke(Command(resume=False), config=config)
            await query.edit_message_text("تمام! ✅ المصروف اتحتفظ بيه.")
        except Exception as e:
            logger.error(f"Delete cancel error: {e}", exc_info=True)
            await query.edit_message_text("تم إلغاء الحذف.")


def setup_handlers(application):
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))
