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
        "update_expense",    # تعديل مصروف موجود — "عدل آخر مصروف", "غير الكاتيجوري"
        "export_report",     # تصدير تقرير — "طلعلي إكسيل", "تقرير شهري", "export"
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
1. log_expense   — recording a new expense ("spent 50 on coffee", "pizza 80 EGP", "اشتريت", "صرفت", "دفعت")
2. query_finance — asking about spending history ("how much today?", "show last 5", "كام صرفت", "وريني")
3. delete_entry  — removing an expense ("delete my last expense", "احذف", "شيل آخر مصروف")
4. update_expense — editing an existing expense ("edit last", "عدل", "غير", "بدل", "صحح")
5. export_report — exporting a report ("طلعلي إكسيل", "export", "تقرير", "report", "Excel")
6. unknown       — unrelated to finance

JSON schema to return:
{{"intent": "log_expense|query_finance|delete_entry|update_expense|export_report|unknown", "clarification_needed": true|false, "clarification_question": "string or null"}}"""),
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
