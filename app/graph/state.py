from typing import Literal
from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    # Required fields
    thread_id: str
    user_message: str
    telegram_id: int

    # Current date (ISO string) — injected by telegram_handler every turn
    current_date: str | None

    # Conversation history: list of ("role", "content") tuples
    conversation_history: list

    # Routing — extended with new intents
    intent: Literal[
        "log_expense",
        "query_finance",
        "delete_entry",
        "update_expense",    # تعديل مصروف موجود
        "export_report",     # تصدير تقرير Excel
        "log_income",        # تسجيل دخل جديد
        "query_balance",     # الرصيد = الدخل - المصاريف
        "add_fixed_payment", # إضافة قسط/فاتورة ثابتة
        "list_fixed_payments", # عرض الأقساط الثابتة
        "unknown"
    ] | None

    # Extraction — single expense
    extracted_data: dict | None

    # Income data
    income_data: dict | None

    # Fixed payment data
    fixed_payment_data: dict | None

    # Split expenses — أكتر من expense في رسالة واحدة
    split_expenses: list[dict] | None

    # Update data — بيانات التعديل على مصروف موجود
    update_data: dict | None

    # Query finance
    query_key: str | None
    query_params: dict | None
    sql_result: list | None

    # Control flow
    needs_clarification: bool
    clarification_question: str | None
    pending_confirmation: bool
    pending_delete: bool | None          # True بعد تأكيد الحذف من المستخدم
    confirmation_action: dict | None
    operation_status: str | None

    # Output
    response: str | None
    error: str | None
