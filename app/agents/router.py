from typing import Literal
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from app.config import settings
from app.graph.state import AgentState


class RouterOutput(BaseModel):
    intent: Literal[
        "log_expense",
        "query_finance",
        "delete_entry",
        "update_expense",      # تعديل مصروف موجود — "عدل", "غير", "صحح"
        "export_report",       # تصدير تقرير — "طلعلي إكسيل", "export"
        "log_income",          # تسجيل دخل — "قبضت", "استلمت", "راتب", "دخل"
        "query_balance",       # الرصيد والمتبقي — "فضلي كام", "المتبقي", "balance"
        "add_fixed_payment",   # إضافة قسط/فاتورة — "عندي قسط", "فاتورة شهرية"
        "list_fixed_payments", # عرض الأقساط — "وريني الأقساط", "الفواتير الثابتة"
        "unknown"
    ] = Field(description="The classified intent of the user's message.")
    clarification_needed: bool = Field(
        description="Whether the intent is unclear and requires clarification."
    )
    clarification_question: str | None = Field(
        description="A friendly question to ask if clarification is needed, else null."
    )


async def route_request(state: AgentState) -> AgentState:
    llm = ChatOpenAI(
        model=settings.router_model,
        api_key=settings.groq_api_key,
        base_url=settings.groq_base_url,
        temperature=0.1,
        max_tokens=256,
    )
    # json_mode works on ALL Groq models; json_schema does not
    structured_llm = llm.with_structured_output(RouterOutput, method="json_mode")

    current_date = state.get("current_date", "Unknown Date")
    prompt_sys = f"""You are a finance assistant router. Classify the user intent and respond ONLY in JSON.

التاريخ والوقت الحالي هو: {current_date}. 
استخدم هذا التاريخ كمرجع أساسي لحساب التواريخ عند ذكر المستخدم لكلمات مثل 'اليوم'، 'أمس'، أو 'الشهر الماضي'.

أنت مسؤول عن تحديد نية المستخدم بدقة (Intent Classification).
يجب عليك تصنيف النية إلى واحدة من الفئات التالية بناءً على هذه القواعد الصارمة:

1. `query_finance`: إذا كان المستخدم يسأل عن معلومات، يطلب إجماليات، أو يستعلم عن تقارير.
   - أمثلة: "ما هو دخلي اليوم؟", "كم صرفت أمس؟", "اعرض مصروفاتي", "What is the income for May 18"
   
2. `log_income`: إذا كان المستخدم يصرح بإضافة مبلغ مالي كدخل أو راتب.
   - أمثلة: "قبضت 1000", "دخل إضافي 500 من شغل بارت تايم"

3. `log_expense`: إذا كان المستخدم يصرح بدفع أو إنفاق مبلغ مالي.
   - أمثلة: "اشتريت قهوة بـ 50", "دفعت فاتورة الكهرباء 200"

4. delete_entry     — removing an expense ("delete my last expense", "احذف", "شيل")
5. update_expense   — editing an existing expense ("عدل", "غير", "بدل", "صحح", "edit")
6. export_report    — exporting a report ("طلعلي إكسيل", "export", "تقرير", "Excel")
7. query_balance    — asking about remaining balance ("فضلي كام", "المتبقي", "balance", "net", "صافي")
8. add_fixed_payment — adding a recurring bill/installment ("عندي قسط", "فاتورة شهرية", "إيجار", "installment", "bill")
9. list_fixed_payments — viewing recurring bills ("وريني الأقساط", "الفواتير الثابتة", "list bills")
10. unknown         — unrelated to finance

تحذير: لا تخلط أبداً بين طلب الاستعلام (Query) وطلب الإضافة (Add). إذا كان المستخدم يسأل (بوجود أدوات استفهام أو بصيغة طلب معلومات)، فالنية حتماً هي `query_finance`.

JSON schema to return:
{{"intent": "log_expense|query_finance|delete_entry|update_expense|export_report|log_income|query_balance|add_fixed_payment|list_fixed_payments|unknown", "clarification_needed": true|false, "clarification_question": "string or null"}}"""

    prompt = ChatPromptTemplate.from_messages([
        ("system", prompt_sys),
        ("placeholder", "{history}"),
        ("human", "{user_message}")
    ])

    result = await (prompt | structured_llm).ainvoke({
        "history": state.get("conversation_history", []),
        "user_message": state["user_message"]
    })

    history = state.get("conversation_history", [])
    history = history + [("user", state["user_message"])]

    # If the router itself is asking for clarification, persist the question too
    if result.clarification_needed and result.clarification_question:
        history = history + [("assistant", result.clarification_question)]

    return {
        **state,
        "intent": result.intent,
        "needs_clarification": result.clarification_needed,
        "clarification_question": result.clarification_question,
        "conversation_history": history
    }
