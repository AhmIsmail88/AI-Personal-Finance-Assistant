import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from langgraph.errors import GraphInterrupt
from langgraph.types import Command
import app.graph.workflow as workflow_module
from app.agents.excel_exporter import export_excel_report

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Handling /start command")
    await update.message.reply_text(
        "مرحباً! 👋 أنا مساعدك المالي الشخصي.\n\n"
        "أستطيع مساعدتك في:\n"
        "• 📝 تسجيل مصاريفك ودخلك\n"
        "• 📊 عرض إحصائيات إنفاقك ورصيدك\n"
        "• 🔔 تذكيرات الأقساط والفواتير الثابتة\n"
        "• 🗑️ حذف أو تعديل مصروف\n"
        "• 📁 تصدير تقرير Excel شامل\n\n"
        "جرب: 'صرفت 50 جنيه على الأكل'"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Handling message: {update.message.text}")
    text    = update.message.text
    user_id = update.effective_user.id

    app_graph = workflow_module.app_graph
    if app_graph is None:
        await update.message.reply_text("البوت لسه بيشتغل، جرب تاني بعد ثانية. 🔄")
        return

    config = {"configurable": {"thread_id": str(user_id)}}

    # ── استرجاع الـ state المحفوظ ────────────────────────────────────────────
    persisted   = await app_graph.aget_state(config)
    prev_values = persisted.values if persisted else {}

    # Sliding window — آخر 20 رسالة فقط
    history = prev_values.get("conversation_history", [])[-20:]

    # التاريخ الحالي بالـ UTC — date_resolver بيحوّله لتوقيت مصر
    current_date = datetime.now(timezone.utc).isoformat()

    initial_state = {
        # نحمل الـ state القديم …
        **prev_values,
        # … ونجدد الـ fields الخاصة بالـ turn الحالي
        "user_message":  text,
        "telegram_id":   user_id,
        "thread_id":     str(user_id),
        "current_date":  current_date,

        # ── Reset كل الـ transient fields ────────────────────────────────
        "intent":               None,
        "extracted_data":       None,
        "split_expenses":       None,
        "update_data":          None,
        "income_data":          None,   # Fix #2
        "fixed_payment_data":   None,   # Fix #2
        "pending_delete":       None,   # Fix #2
        "query_key":            None,
        "query_params":         None,
        "sql_result":           None,
        "needs_clarification":  False,
        "clarification_question": None,
        "pending_confirmation": False,
        "confirmation_action":  None,
        "operation_status":     None,
        "response":             None,
        "error":                None,

        "conversation_history": history,
    }

    try:
        result = await app_graph.ainvoke(initial_state, config=config)

        # ── Export Excel ──────────────────────────────────────────────────
        if result.get("intent") == "export_report" and result.get("sql_result"):
            await update.message.reply_text("جاري تجهيز التقرير... ⏳")

            raw = result["sql_result"]
            # db_agent يرجع dict {"expenses":[], "income":[]}
            # guard ضد أي format قديم
            excel_data = raw if isinstance(raw, dict) else {"expenses": raw, "income": []}

            success = await export_excel_report(
                sql_result=excel_data,
                bot=context.bot,
                chat_id=user_id,
                current_date=current_date,
            )
            if not success:
                await update.message.reply_text("حصل خطأ أثناء توليد التقرير. حاول تاني. 🙏")
            return

        # ── رد عادي ──────────────────────────────────────────────────────
        if result.get("needs_clarification") and not result.get("response"):
            await update.message.reply_text(result["clarification_question"])
        elif result.get("response"):
            await update.message.reply_text(result["response"])
        else:
            await update.message.reply_text("مش متأكد إزاي أساعدك في ده.")

    except GraphInterrupt:
        # الـ graph اتوقف عند confirm_delete — نعرض أزرار Yes/No
        keyboard = [[
            InlineKeyboardButton("✅ نعم، احذف",  callback_data="delete_confirm"),
            InlineKeyboardButton("❌ لأ، احتفظ", callback_data="delete_cancel"),
        ]]
        await update.message.reply_text(
            "⚠️ هل أنت متأكد من حذف آخر مصروف؟",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Error in handle_message: {e}", exc_info=True)
        await update.message.reply_text("حصل خطأ غير متوقع. حاول تاني. 🙏")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()

    user_id   = update.effective_user.id
    app_graph = workflow_module.app_graph
    if app_graph is None:
        await query.edit_message_text("البوت لسه بيشتغل، جرب تاني. 🔄")
        return

    config = {"configurable": {"thread_id": str(user_id)}}

    if query.data == "delete_confirm":
        try:
            result = await app_graph.ainvoke(Command(resume=True), config=config)
            await query.edit_message_text(result.get("response", "✅ تم الحذف بنجاح!"))
        except Exception as e:
            logger.error(f"Delete confirm error: {e}", exc_info=True)
            await query.edit_message_text("حصل خطأ أثناء الحذف. حاول تاني. 🙏")
    else:
        try:
            await app_graph.ainvoke(Command(resume=False), config=config)
            await query.edit_message_text("تمام! ✅ المصروف اتحتفظ بيه.")
        except Exception as e:
            logger.error(f"Delete cancel error: {e}", exc_info=True)
            await query.edit_message_text("تم إلغاء الحذف.")


def setup_handlers(application):
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))
