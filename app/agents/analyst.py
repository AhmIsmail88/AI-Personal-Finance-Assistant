from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from app.config import settings
from app.graph.state import AgentState

SYSTEM = """You are a warm, professional personal finance assistant.
Write concise, friendly responses. DO NOT calculate anything — all numbers come from the database.
Use relevant emojis naturally. Keep it to 1-3 sentences.
Always respond in the same language the user used (Arabic or English)."""


async def summarize_response(state: AgentState) -> AgentState:
    history = state.get("conversation_history", [])

    # ── Clarification needed (from router OR extractor) ─────────────────────
    if state.get("needs_clarification"):
        question = state.get("clarification_question", "Could you please clarify?")
        # The question is already in history (added by router/extractor),
        # but if it somehow isn't, append it now.
        if not history or history[-1] != ("assistant", question):
            history = history + [("assistant", question)]
        return {
            **state,
            "response": question,
            "conversation_history": history,
        }

    # ── Hard error ───────────────────────────────────────────────────────────
    if state.get("error"):
        msg = "I ran into a bit of trouble. Please try again! 🙏"
        return {
            **state,
            "response": msg,
            "conversation_history": history + [("assistant", msg)],
        }

    intent = state.get("intent")
    status = state.get("operation_status")
    extracted = state.get("extracted_data", {})
    sql_result = state.get("sql_result")
    split_expenses = state.get("split_expenses")

    # ── Unknown / off-topic intent — politely redirect ───────────────────────
    if intent == "unknown" or (not intent):
        msg = (
            "I'm your personal finance assistant 💰 — I can help you:\n"
            "• Log expenses (e.g. *'spent 80 EGP on pizza'*)\n"
            "• Check your spending (e.g. *'how much did I spend today?'*)\n"
            "• Delete or update your last entry\n"
            "• Export a full report to Excel 📊\n\n"
            "What would you like to do?"
        )
        return {
            **state,
            "response": msg,
            "conversation_history": history + [("assistant", msg)],
        }

    # ── Export report — analyst steps aside, handler sends the file ──────────
    if intent == "export_report" and sql_result:
        # Return no response text — telegram_handler will send the Excel file
        return {
            **state,
            "response": None,
        }

    # ── Build the human_text prompt for the LLM ──────────────────────────────
    elif intent == "log_income" and status == "success":
        income_data = state.get("income_data", {})
        source_map = {
            "salary": "راتب شهري 💼",
            "freelance": "فريلانس 💻",
            "part_time": "بارت تايم ⏰",
            "other": "دخل إضافي 💵",
        }
        source_label = source_map.get(income_data.get("source_type", "other"), "دخل")
        human_text = (
            f"تم تسجيل دخل: {income_data.get('amount')} {income_data.get('currency','EGP')} "
            f"({source_label}). "
            "Write a warm 1-2 sentence Arabic confirmation with emoji."
        )

    elif intent == "query_balance" and sql_result:
        row = sql_result[0]
        human_text = (
            f"إجمالي الدخل: {row.get('total_income')} EGP\n"
            f"إجمالي المصاريف: {row.get('total_expenses')} EGP\n"
            f"الأقساط الشهرية الثابتة: {row.get('total_fixed_monthly')} EGP\n"
            f"صافي المتبقي: {row.get('net_balance')} EGP\n\n"
            "Summarize this as a clear financial snapshot in Arabic with emojis. "
            "DO NOT recalculate — use the numbers as-is."
        )

    elif intent == "add_fixed_payment" and status == "success":
        fp = state.get("fixed_payment_data", {})
        human_text = (
            f"تم إضافة {fp.get('name')} بمبلغ {fp.get('amount')} EGP "
            f"في يوم {fp.get('due_day')} من كل شهر. "
            f"سيتم التذكير قبل {fp.get('remind_days_before', 3)} أيام. "
            "Write a short Arabic confirmation with emoji."
        )

    elif intent == "list_fixed_payments" and sql_result:
        items = "\n".join(
            f"- {r['name']}: {r['amount']} {r['currency']} — يوم {r['due_day']}"
            for r in sql_result
        )
        total = sum(float(r["amount"]) for r in sql_result)
        human_text = (
            f"الأقساط والفواتير الثابتة:\n{items}\n"
            f"الإجمالي الشهري: {round(total, 2)} EGP\n\n"
            "Present this as a clean Arabic list with emojis. DO NOT recalculate totals."
        )

    elif intent == "log_expense" and status == "success":
        if split_expenses and len(split_expenses) > 1:
            # Multiple expenses logged in one message
            items_summary = ", ".join(
                f"{e.get('item')} ({e.get('amount')} {e.get('currency', 'EGP')})"
                for e in split_expenses
            )
            human_text = (
                f"تم تسجيل {len(split_expenses)} مصاريف بنجاح: {items_summary}.\n"
                "Write a friendly confirmation mentioning all items with a relevant emoji."
            )
        else:
            human_text = (
                f"The user logged: {extracted.get('item')} for {extracted.get('amount')} "
                f"{extracted.get('currency', 'EGP')} (category: {extracted.get('category')}).\n"
                "Write a friendly 1-2 sentence confirmation with a relevant emoji."
            )
    elif intent == "update_expense" and status == "success":
        update_data = state.get("update_data", {})
        human_text = (
            f"The user's last expense was updated. Changes: {update_data}.\n"
            "Write a brief, friendly Arabic+emoji confirmation of the update."
        )
    elif intent == "delete_entry" and status == "success":
        human_text = "The user's last expense was deleted. Write a brief, friendly confirmation."
    elif sql_result:
        human_text = (
            f"The user asked: '{state.get('user_message')}'\n\n"
            f"Database results: {sql_result}\n\n"
            "Summarize this naturally. DO NOT do any math yourself."
        )
    else:
        msg = "No data found for that request. Try asking differently!"
        return {
            **state,
            "response": msg,
            "conversation_history": history + [("assistant", msg)],
        }

    llm = ChatOpenAI(
        model=settings.analyst_model,
        api_key=settings.groq_api_key,
        base_url=settings.groq_base_url,
        temperature=0.7,
        max_tokens=300,
    )

    result = await llm.ainvoke([SystemMessage(content=SYSTEM), HumanMessage(content=human_text)])
    msg = result.content

    return {
        **state,
        "response": msg,
        "conversation_history": history + [("assistant", msg)],
    }
