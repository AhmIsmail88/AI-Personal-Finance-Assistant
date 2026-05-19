from sqlalchemy import select, text
from app.database.connection import AsyncSessionLocal
from app.database.models import User, Category, Expense, Income, FixedPayment
from app.graph.state import AgentState
from app.agents.date_resolver import (
    detect_date_intent,
    resolve_date_params,
    has_date_keyword,
)
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

# ── Query template library ────────────────────────────────────────────────────
# All aggregations happen here in SQL — never in LLM (No LLM Math rule)

QUERY_TEMPLATES = {
    # ── All-time summaries ──────────────────────────────────────────────────
    "total_all_time": """
        SELECT SUM(amount) AS total, COUNT(*) AS count, currency
        FROM expenses
        WHERE user_id = :user_id
        GROUP BY currency
    """,
    "average_per_transaction": """
        SELECT
            ROUND(AVG(amount)::numeric, 2) AS average_per_transaction,
            ROUND(SUM(amount)::numeric, 2) AS total_spent,
            COUNT(*) AS transaction_count,
            ROUND(MIN(amount)::numeric, 2) AS min_transaction,
            ROUND(MAX(amount)::numeric, 2) AS max_transaction,
            currency
        FROM expenses
        WHERE user_id = :user_id
        GROUP BY currency
    """,
    "average_by_category": """
        SELECT c.name AS category,
            ROUND(AVG(e.amount)::numeric, 2) AS average,
            ROUND(SUM(e.amount)::numeric, 2) AS total,
            COUNT(*) AS count
        FROM expenses e JOIN categories c ON e.category_id = c.id
        WHERE e.user_id = :user_id
        GROUP BY c.name ORDER BY average DESC
    """,

    # ── Category breakdown ──────────────────────────────────────────────────
    # Bug #7 fix: separate all-time vs. date-ranged breakdown
    "total_by_category_alltime": """
        SELECT c.name, ROUND(SUM(e.amount)::numeric, 2) AS total
        FROM expenses e JOIN categories c ON e.category_id = c.id
        WHERE e.user_id = :user_id
        GROUP BY c.name ORDER BY total DESC
    """,
    "total_by_category": """
        SELECT c.name, ROUND(SUM(e.amount)::numeric, 2) AS total
        FROM expenses e JOIN categories c ON e.category_id = c.id
        WHERE e.user_id = :user_id AND e.created_at >= :since
        GROUP BY c.name ORDER BY total DESC
    """,

    # ── Period totals ───────────────────────────────────────────────────────
    # Fix: total_this_month now uses :since from date_resolver (not NOW())
    "total_this_month": """
        SELECT ROUND(SUM(amount)::numeric, 2) AS total, currency FROM expenses
        WHERE user_id = :user_id
          AND created_at >= :since
        GROUP BY currency
    """,
    "total_today": """
        SELECT ROUND(SUM(amount)::numeric, 2) AS total, currency FROM expenses
        WHERE user_id = :user_id
          AND DATE(created_at) = :target_date
        GROUP BY currency
    """,
    "total_yesterday": """
        SELECT ROUND(SUM(amount)::numeric, 2) AS total, currency FROM expenses
        WHERE user_id = :user_id
          AND DATE(created_at) = :target_date
        GROUP BY currency
    """,
    "total_this_week": """
        SELECT ROUND(SUM(amount)::numeric, 2) AS total, currency FROM expenses
        WHERE user_id = :user_id
          AND created_at >= :since
        GROUP BY currency
    """,

    # ── Detailed reports ────────────────────────────────────────────────────
    "report_half_year": """
        SELECT
            TO_CHAR(DATE_TRUNC('month', created_at), 'YYYY-MM') AS month,
            ROUND(SUM(amount)::numeric, 2) AS total,
            currency
        FROM expenses
        WHERE user_id = :user_id AND created_at >= :since
        GROUP BY DATE_TRUNC('month', created_at), currency
        ORDER BY month
    """,
    "report_yearly": """
        SELECT
            TO_CHAR(DATE_TRUNC('month', created_at), 'YYYY-MM') AS month,
            ROUND(SUM(amount)::numeric, 2) AS total,
            currency
        FROM expenses
        WHERE user_id = :user_id AND created_at >= :since
        GROUP BY DATE_TRUNC('month', created_at), currency
        ORDER BY month
    """,

    # ── Recent listings ─────────────────────────────────────────────────────
    "recent_expenses": """
        SELECT item, amount, currency, created_at FROM expenses
        WHERE user_id = :user_id ORDER BY created_at DESC LIMIT :limit
    """,
}


def _select_query(user_message: str, user_id: int) -> tuple[str, dict]:
    """
    Selects the appropriate query template and parameters from the user message.
    Uses date_resolver for Arabic + English date keyword detection.
    """
    msg = user_message.lower()

    # Average / mean queries — must come before general keyword checks
    if any(k in msg for k in ["average", "avg", "mean", "per transaction", "rate",
                               "متوسط", "معدل"]):
        if any(k in msg for k in ["category", "categories", "breakdown",
                                   "فئة", "كاتيجوري", "تفصيل"]):
            return "average_by_category", {"user_id": user_id}
        return "average_per_transaction", {"user_id": user_id}

    # ── Date-based queries via date_resolver ──────────────────────────────
    date_key = detect_date_intent(user_message)
    if date_key:
        now_utc = datetime.now(timezone.utc)
        params = resolve_date_params(date_key, now_utc)
        params["user_id"] = user_id
        return date_key, params

    # ── Category breakdown — Bug #7 fix ──────────────────────────────────
    if any(k in msg for k in ["category", "categories", "breakdown", "by category",
                               "فئة", "كاتيجوري", "تفصيلة", "تفصيل"]):
        return "total_by_category_alltime", {"user_id": user_id}

    # ── Listing / recent ─────────────────────────────────────────────────
    if any(k in msg for k in ["last", "recent", "show", "list",
                               "آخر", "الأخيرة", "وريني", "اعرضلي"]):
        return "recent_expenses", {"user_id": user_id, "limit": 5}

    if any(k in msg for k in ["history", "تاريخ", "سجل"]):
        return "recent_expenses", {"user_id": user_id, "limit": 10}

    # ── Generic totals ────────────────────────────────────────────────────
    if any(k in msg for k in ["how much", "total", "so far", "spent", "all",
                               "كام", "إجمالي", "مجموع", "كم", "صرفت"]):
        return "total_all_time", {"user_id": user_id}

    # Fallback
    return "recent_expenses", {"user_id": user_id, "limit": 5}


# ── Main operation function ───────────────────────────────────────────────────

async def execute_operation(state: AgentState) -> AgentState:
    async with AsyncSessionLocal() as session:
        try:
            # 1. Ensure User exists (upsert)
            user_stmt = select(User).where(User.telegram_id == state["telegram_id"])
            user_result = await session.execute(user_stmt)
            db_user = user_result.scalar_one_or_none()

            if not db_user:
                db_user = User(telegram_id=state["telegram_id"])
                session.add(db_user)
                await session.flush()

            # ── 2a. Log expense (single or split) ────────────────────────
            if state.get("intent") == "log_expense":
                if state.get("split_expenses"):
                    for exp_data in state["split_expenses"]:
                        cat_stmt = select(Category).where(Category.name == exp_data["category"])
                        cat_result = await session.execute(cat_stmt)
                        db_category = cat_result.scalar_one_or_none()
                        if not db_category:
                            continue
                        session.add(Expense(
                            user_id=state["telegram_id"],
                            category_id=db_category.id,
                            item=exp_data["item"],
                            amount=exp_data["amount"],
                            currency=exp_data.get("currency", "EGP"),
                        ))
                    await session.commit()
                    return {**state, "operation_status": "success"}

                data = state.get("extracted_data")
                if not data:
                    return {**state, "response": "I couldn't find the expense details to log."}

                cat_stmt = select(Category).where(Category.name == data["category"])
                cat_result = await session.execute(cat_stmt)
                db_category = cat_result.scalar_one_or_none()

                if not db_category:
                    return {**state, "response": f"Unknown category '{data['category']}'. Please try again."}

                session.add(Expense(
                    user_id=state["telegram_id"],
                    category_id=db_category.id,
                    item=data["item"],
                    amount=data["amount"],
                    currency=data.get("currency", "EGP"),
                ))
                await session.commit()
                return {**state, "operation_status": "success"}

            # ── 2b. Query finance ─────────────────────────────────────────
            elif state.get("intent") == "query_finance":
                query_key = state.get("query_key") or None
                params = state.get("query_params") or None

                if not query_key or not params:
                    query_key, params = _select_query(
                        state.get("user_message", ""),
                        state["telegram_id"]
                    )

                template = QUERY_TEMPLATES.get(query_key)
                if not template:
                    return {**state, "response": "I'm not sure how to query that. Try asking for your monthly total or recent expenses."}

                result = await session.execute(text(template), params)
                sql_result = [dict(row._mapping) for row in result.all()]

                if not sql_result or all(v is None for row in sql_result for v in row.values()):
                    return {**state, "response": "No expenses found yet! Start by logging one."}

                return {**state, "sql_result": sql_result, "query_key": query_key}

            # ── 2c. Delete entry ──────────────────────────────────────────
            # Bug #1 fix + Resume fix:
            # pending_delete=True is set by confirm_delete node after user confirms
            elif state.get("intent") == "delete_entry" or state.get("pending_delete") == True:  # noqa: E712
                if state.get("pending_delete") == True:  # noqa: E712
                    last_expense_stmt = (
                        select(Expense)
                        .where(Expense.user_id == state["telegram_id"])
                        .order_by(Expense.created_at.desc())
                        .limit(1)
                    )
                    last_expense_res = await session.execute(last_expense_stmt)
                    last_expense = last_expense_res.scalar_one_or_none()

                    if last_expense:
                        await session.delete(last_expense)
                        await session.commit()
                        return {**state, "operation_status": "success", "pending_delete": False}
                    else:
                        return {**state, "response": "No expenses found to delete.", "pending_delete": False}

                # pending_delete is False → user cancelled, nothing to do
                return {**state, "operation_status": "cancelled"}

            # ── 2d. Update expense ────────────────────────────────────────
            elif state.get("intent") == "update_expense":
                update_data = state.get("update_data")
                if not update_data:
                    return {**state, "response": "ما عندي بيانات كافية للتعديل. حاول تاني."}

                last_stmt = (
                    select(Expense)
                    .where(Expense.user_id == state["telegram_id"])
                    .order_by(Expense.created_at.desc())
                    .limit(1)
                )
                last_res = await session.execute(last_stmt)
                last_expense = last_res.scalar_one_or_none()

                if not last_expense:
                    return {**state, "response": "ما فيش مصاريف محفوظة للتعديل عليها."}

                if update_data.get("new_amount"):
                    last_expense.amount = update_data["new_amount"]
                if update_data.get("new_item"):
                    last_expense.item = update_data["new_item"]
                if update_data.get("new_category"):
                    cat_stmt = select(Category).where(
                        Category.name == update_data["new_category"]
                    )
                    cat_res = await session.execute(cat_stmt)
                    new_cat = cat_res.scalar_one_or_none()
                    if new_cat:
                        last_expense.category_id = new_cat.id

                await session.commit()
                return {**state, "operation_status": "success"}

            # ── 2e. Export report ─────────────────────────────────────────
            elif state.get("intent") == "export_report":
                query = """
                    SELECT e.item, e.amount, e.currency, e.created_at, c.name AS category
                    FROM expenses e
                    JOIN categories c ON e.category_id = c.id
                    WHERE e.user_id = :user_id
                    ORDER BY e.created_at DESC
                    LIMIT 1000
                """
                result = await session.execute(text(query), {"user_id": state["telegram_id"]})
                sql_result = [dict(row._mapping) for row in result.all()]

                if not sql_result:
                    return {**state, "response": "ما فيش مصاريف لتصديرها بعد! ابدأ بتسجيل مصاريفك أولاً."}

                return {**state, "sql_result": sql_result, "query_key": "export_report"}

            # ── 2f. Log income ────────────────────────────────────────────
            elif state.get("intent") == "log_income":
                income_data = state.get("income_data")
                if not income_data:
                    return {**state, "response": "ما فيش بيانات دخل. حاول تاني."}

                session.add(Income(
                    user_id     = state["telegram_id"],
                    source_type = income_data["source_type"],
                    description = income_data.get("description"),
                    amount      = income_data["amount"],
                    currency    = income_data.get("currency", "EGP"),
                ))
                await session.commit()
                return {**state, "operation_status": "success"}

            # ── 2g. Query balance (income - expenses) ─────────────────────
            elif state.get("intent") == "query_balance":
                balance_query = """
                    SELECT
                        COALESCE((
                            SELECT SUM(amount) FROM income
                            WHERE user_id = :user_id
                        ), 0) AS total_income,
                        COALESCE((
                            SELECT SUM(amount) FROM expenses
                            WHERE user_id = :user_id
                        ), 0) AS total_expenses,
                        COALESCE((
                            SELECT SUM(amount) FROM fixed_payments
                            WHERE user_id = :user_id AND is_active = TRUE
                        ), 0) AS total_fixed_monthly
                """
                result = await session.execute(
                    text(balance_query), {"user_id": state["telegram_id"]}
                )
                row = result.fetchone()
                if row:
                    d = dict(row._mapping)
                    d["net_balance"] = float(d["total_income"]) - float(d["total_expenses"])
                    return {**state, "sql_result": [d], "query_key": "query_balance"}
                return {**state, "response": "ما فيش بيانات كافية لحساب الرصيد."}

            # ── 2h. Add fixed payment ─────────────────────────────────────
            elif state.get("intent") == "add_fixed_payment":
                fp_data = state.get("fixed_payment_data")
                if not fp_data:
                    return {**state, "response": "ما فيش بيانات كافية. حاول تاني."}

                session.add(FixedPayment(
                    user_id            = state["telegram_id"],
                    name               = fp_data["name"],
                    amount             = fp_data["amount"],
                    currency           = fp_data.get("currency", "EGP"),
                    category           = fp_data["category"],
                    due_day            = fp_data["due_day"],
                    remind_days_before = fp_data.get("remind_days_before", 3),
                    is_active          = True,
                ))
                await session.commit()
                return {**state, "operation_status": "success"}

            # ── 2i. List fixed payments ───────────────────────────────────
            elif state.get("intent") == "list_fixed_payments":
                list_query = """
                    SELECT name, amount, currency, category, due_day, remind_days_before
                    FROM fixed_payments
                    WHERE user_id = :user_id AND is_active = TRUE
                    ORDER BY due_day
                """
                result = await session.execute(
                    text(list_query), {"user_id": state["telegram_id"]}
                )
                rows = [dict(row._mapping) for row in result.all()]
                if not rows:
                    return {**state, "response": "ما فيش أقساط أو فواتير ثابتة مسجلة بعد. 📋"}
                return {**state, "sql_result": rows, "query_key": "list_fixed_payments"}

            return state

        except Exception as e:
            logger.error(f"Database error: {e}", exc_info=True)
            return {
                **state,
                "error": str(e),
                "response": "Sorry, I encountered a database error. Please try again.",
            }
