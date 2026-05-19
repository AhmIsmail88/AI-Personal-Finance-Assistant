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

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a finance assistant router. Classify the user intent and respond ONLY in JSON.

Categories:
1. log_expense      — recording a new expense ("spent 50 on coffee", "صرفت", "اشتريت", "دفعت")
2. query_finance    — asking about spending history ("how much today?", "كام صرفت", "وريني")
3. delete_entry     — removing an expense ("delete my last expense", "احذف", "شيل")
4. update_expense   — editing an existing expense ("عدل", "غير", "بدل", "صحح", "edit")
5. export_report    — exporting a report ("طلعلي إكسيل", "export", "تقرير", "Excel")
6. log_income       — recording income received ("قبضت", "استلمت", "راتب", "دخل", "received", "got paid")
7. query_balance    — asking about remaining balance ("فضلي كام", "المتبقي", "balance", "net", "صافي")
8. add_fixed_payment — adding a recurring bill/installment ("عندي قسط", "فاتورة شهرية", "إيجار", "installment", "bill")
9. list_fixed_payments — viewing recurring bills ("وريني الأقساط", "الفواتير الثابتة", "list bills")
10. unknown         — unrelated to finance

JSON schema to return:
{{"intent": "log_expense|query_finance|delete_entry|update_expense|export_report|log_income|query_balance|add_fixed_payment|list_fixed_payments|unknown", "clarification_needed": true|false, "clarification_question": "string or null"}}"""),
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
