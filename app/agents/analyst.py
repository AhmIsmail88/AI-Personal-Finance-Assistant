from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from app.config import settings
from app.graph.state import AgentState

SYSTEM = """\
أنت مساعد مالي شخصي دافئ ومحترف.
- اكتب ردوداً موجزة وودية (1-3 جمل).
- لا تحسب أي أرقام بنفسك — كل الأرقام تأتي من قاعدة البيانات.
- استخدم الإيموجي بشكل طبيعي.
- رد دائماً بنفس لغة المستخدم (عربي أو إنجليزي).
- لا تذكر أي تفاصيل تقنية أو أخطاء للمستخدم.
"""


async def summarize_response(state: AgentState) -> AgentState:
    history = state.get("conversation_history", [])

    # ── توضيح مطلوب ──────────────────────────────────────────────────────────
    if state.get("needs_clarification"):
        question = state.get("clarification_question", "ممكن توضح أكتر؟ 🙏")
        if not history or history[-1] != ("assistant", question):
            history = history + [("assistant", question)]
        return {
            **state,
            "response": question,
            "conversation_history": history,
        }

    # ── خطأ ──────────────────────────────────────────────────────────────────
    if state.get("error"):
        msg = "حصل خطأ غير متوقع، حاول تاني. 🙏"
        return {
            **state,
            "response": msg,
            "conversation_history": history + [("assistant", msg)],
        }

    intent   = state.get("intent")
    status   = state.get("operation_status")
    extracted    = state.get("extracted_data") or {}
    sql_result   = state.get("sql_result")
    split_expenses = state.get("split_expenses")

    # ── Intent غير معروف ─────────────────────────────────────────────────────
    if intent == "unknown" or (not intent):
        msg = (
            "أنا مساعدك المالي الشخصي 💰 — أقدر أساعدك في:\n"
            "• تسجيل مصاريفك 📝\n"
            "• تسجيل دخلك 💵\n"
            "• الاستعلام عن إنفاقك ورصيدك 📊\n"
            "• حذف أو تعديل مصروف 🗑️\n"
            "• تصدير تقرير Excel 📁\n\n"
            "جرب: 'صرفت 50 جنيه على الأكل'"
        )
        return {
            **state,
            "response": msg,
            "conversation_history": history + [("assistant", msg)],
        }

    # ── Export — الـ handler هيبعت الملف مباشرة ──────────────────────────────
    if intent == "export_report" and sql_result:
        return {**state, "response": None}

    # ── بناء الـ human_text للـ LLM ───────────────────────────────────────────
    human_text = None

    if intent == "log_income" and status == "success":
        income_data = state.get("income_data") or {}
        source_map = {
            "salary":    "راتب شهري 💼",
            "freelance": "فريلانس 💻",
            "part_time": "بارت تايم ⏰",
            "other":     "دخل إضافي 💵",
        }
        source_label = source_map.get(income_data.get("source_type", "other"), "دخل")
        human_text = (
            f"تم تسجيل دخل بنجاح: {income_data.get('amount')} {income_data.get('currency','EGP')} "
            f"({source_label}).\n"
            "اكتب رسالة تأكيد عربية ودية بإيموجي مناسب. جملة أو جملتين."
        )

    elif intent == "query_balance" and sql_result:
        row = sql_result[0]
        human_text = (
            f"نتائج قاعدة البيانات:\n"
            f"- إجمالي الدخل: {row.get('total_income')} EGP\n"
            f"- إجمالي المصاريف: {row.get('total_expenses')} EGP\n"
            f"- الأقساط الثابتة الشهرية: {row.get('total_fixed_monthly')} EGP\n"
            f"- صافي المتبقي: {row.get('net_balance')} EGP\n\n"
            "قدّم هذه الأرقام كلقطة مالية واضحة بالعربي مع إيموجي. "
            "لا تعيد حساب أي رقم — استخدم الأرقام كما هي."
        )

    elif intent == "add_fixed_payment" and status == "success":
        fp = state.get("fixed_payment_data") or {}
        human_text = (
            f"تم إضافة '{fp.get('name')}' بمبلغ {fp.get('amount')} EGP "
            f"في يوم {fp.get('due_day')} من كل شهر. "
            f"التذكير سيُرسل قبل {fp.get('remind_days_before', 3)} أيام.\n"
            "اكتب تأكيداً عربياً قصيراً بإيموجي."
        )

    elif intent == "list_fixed_payments" and sql_result:
        items = "\n".join(
            f"- {r['name']}: {r['amount']} {r.get('currency','EGP')} — يوم {r['due_day']}"
            for r in sql_result
        )
        total = sum(float(r["amount"]) for r in sql_result)
        human_text = (
            f"الأقساط والفواتير الثابتة المسجلة:\n{items}\n"
            f"الإجمالي الشهري: {round(total, 2)} EGP\n\n"
            "اعرضها كقائمة عربية واضحة بإيموجي. لا تعيد حساب الإجمالي."
        )

    elif intent == "log_expense" and status == "success":
        if split_expenses and len(split_expenses) > 1:
            items_summary = ", ".join(
                f"{e.get('item')} ({e.get('amount')} {e.get('currency', 'EGP')})"
                for e in split_expenses
            )
            human_text = (
                f"تم تسجيل {len(split_expenses)} مصاريف بنجاح: {items_summary}.\n"
                "اكتب تأكيداً عربياً ودياً يذكر كل البنود مع إيموجي مناسب."
            )
        else:
            human_text = (
                f"تم تسجيل مصروف: {extracted.get('item')} "
                f"بمبلغ {extracted.get('amount')} {extracted.get('currency', 'EGP')} "
                f"(فئة: {extracted.get('category')}).\n"
                "اكتب تأكيداً عربياً ودياً بجملة أو جملتين مع إيموجي مناسب."
            )

    elif intent == "update_expense" and status == "success":
        update_data = state.get("update_data") or {}
        human_text = (
            f"تم تحديث آخر مصروف بنجاح. التغييرات: {update_data}.\n"
            "اكتب تأكيداً عربياً قصيراً ودياً بإيموجي."
        )

    elif intent == "delete_entry" and status == "success":
        human_text = (
            "تم حذف آخر مصروف بنجاح.\n"
            "اكتب تأكيداً عربياً قصيراً ودياً بإيموجي."
        )

    elif intent == "delete_entry" and status == "cancelled":
        msg = "تمام! ✅ المصروف اتحتفظ بيه."
        return {
            **state,
            "response": msg,
            "conversation_history": history + [("assistant", msg)],
        }

    elif sql_result:
        query_key = state.get("query_key", "")
        user_msg  = state.get("user_message", "")

        if query_key and query_key.startswith("income_"):
            if query_key == "recent_income":
                items = "\n".join(
                    f"- {r.get('source_type','other')}: {r.get('amount')} {r.get('currency','EGP')} "
                    f"({r.get('description') or 'بدون وصف'}) — {str(r.get('received_at',''))[:10]}"
                    for r in sql_result
                )
                human_text = (
                    f"المستخدم سأل: '{user_msg}'\n\n"
                    f"سجلات الدخل من قاعدة البيانات:\n{items}\n\n"
                    "اعرضها كتاريخ دخل عربي واضح بإيموجي. لا تجري أي حسابات."
                )
            else:
                human_text = (
                    f"المستخدم سأل: '{user_msg}'\n\n"
                    f"نتائج استعلام الدخل من قاعدة البيانات: {sql_result}\n\n"
                    "هذه بيانات دخل (مش مصاريف). لخّصها بالعربي بوضوح مع إيموجي. "
                    "لا تحسب أي رقم — استخدم الأرقام كما هي."
                )
        else:
            human_text = (
                f"المستخدم سأل: '{user_msg}'\n\n"
                f"نتائج قاعدة البيانات: {sql_result}\n\n"
                "لخّص هذه النتائج بشكل طبيعي وودي بالعربي. لا تجري أي حسابات."
            )

    # ── مفيش بيانات ──────────────────────────────────────────────────────────
    if human_text is None:
        msg = "ما لقيتش بيانات لهذا الطلب. جرب بطريقة تانية! 🤔"
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
