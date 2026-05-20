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
        "update_expense",
        "export_report",
        "log_income",
        "query_balance",
        "add_fixed_payment",
        "list_fixed_payments",
        "unknown"
    ] = Field(description="The classified intent of the user's message.")
    clarification_needed: bool = Field(
        description="Whether the intent is unclear and requires clarification."
    )
    clarification_question: str | None = Field(
        description="A friendly question to ask if clarification is needed, else null."
    )


ROUTER_SYSTEM = """\
أنت مساعد مالي ذكي. مهمتك الوحيدة هي تصنيف نية المستخدم وإرجاع JSON فقط.

قواعد التصنيف — اقرأها بترتيب من الأعلى للأسفل واختر أول تصنيف ينطبق:

1. log_expense — المستخدم يُعلن إنه صرف أو دفع فعلاً
   أمثلة: "اشتريت قهوة بـ50", "دفعت إيجار 2000", "spent 80 on pizza"
   ⚠️ لازم يكون فيه فعل إنفاق — مش مجرد سؤال

2. log_income — المستخدم يُعلن إنه استلم أو قبض مبلغ
   أمثلة: "قبضت 5000 راتب", "استلمت 1200 فريلانس", "received my salary"
   ⚠️ لازم يكون فيه فعل استلام — مش مجرد سؤال

3. query_finance — المستخدم يسأل عن أرقام أو تاريخ إنفاق/دخل
   أمثلة: "كام صرفت؟", "ما هو دخلي؟", "وريني مصاريف امبارح", "how much today?"
   ⚠️ أي سؤال بأداة استفهام (كام، ما، كيف، وريني) = query_finance

4. query_balance — يسأل عن الرصيد أو المتبقي
   أمثلة: "فضلي كام؟", "صافي دخلي", "balance", "المتبقي عندي"

5. export_report — يطلب ملف أو تقرير للتحميل
   أمثلة: "طلعلي إكسيل", "عايز تقرير", "export", "Excel report"
   ⚠️ "تقرير" وحدها بدون طلب تحميل = query_finance مش export_report

6. update_expense — يريد تعديل مصروف موجود
   أمثلة: "عدل آخر مصروف", "غير الكاتيجوري", "صحح المبلغ"

7. delete_entry — يريد حذف مصروف
   أمثلة: "احذف آخر مصروف", "شيل اللي سجلته", "delete last"

8. add_fixed_payment — يريد إضافة قسط أو فاتورة شهرية ثابتة
   أمثلة: "عندي قسط سيارة 800", "فاتورة إيجار شهرية", "add monthly bill"

9. list_fixed_payments — يريد يشوف الأقساط المسجلة
   أمثلة: "وريني الأقساط", "الفواتير الثابتة", "list my bills"

10. unknown — غير متعلق بالمالية

⚠️ قاعدة ذهبية: لو الرسالة فيها علامة استفهام أو كلمات (كام، ما، كيف، وريني، اعرض، show, how much, what) → query_finance دايماً.
⚠️ قاعدة ذهبية: "تقرير إكسيل" أو "export" = export_report. "تقرير" لوحدها = query_finance.

أرجع JSON فقط بالشكل ده:
{"intent": "...", "clarification_needed": false, "clarification_question": null}
"""


async def route_request(state: AgentState) -> AgentState:
    llm = ChatOpenAI(
        model=settings.router_model,
        api_key=settings.groq_api_key,
        base_url=settings.groq_base_url,
        temperature=0.0,   # صفر عشان التصنيف يكون حتمي مش إبداعي
        max_tokens=150,    # التصنيف مش محتاج أكتر من كده
    )
    structured_llm = llm.with_structured_output(RouterOutput, method="json_mode")

    prompt = ChatPromptTemplate.from_messages([
        ("system", ROUTER_SYSTEM),
        ("placeholder", "{history}"),
        ("human", "{user_message}")
    ])

    result = await (prompt | structured_llm).ainvoke({
        "history": state.get("conversation_history", [])[-10:],  # آخر 10 بس للـ router
        "user_message": state["user_message"]
    })

    history = state.get("conversation_history", [])
    history = history + [("user", state["user_message"])]

    if result.clarification_needed and result.clarification_question:
        history = history + [("assistant", result.clarification_question)]

    return {
        **state,
        "intent": result.intent,
        "needs_clarification": result.clarification_needed,
        "clarification_question": result.clarification_question,
        "conversation_history": history
    }
