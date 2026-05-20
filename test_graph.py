import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import codecs
from dotenv import load_dotenv

load_dotenv()
sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())

from app.database.connection import init_db
from app.graph.workflow import init_graph
import app.graph.workflow as workflow_module
from datetime import datetime, timezone


def _make_state(prev: dict, text: str, user_id: int) -> dict:
    """Helper — builds a clean per-turn state with all transient fields reset."""
    history = prev.get("conversation_history", [])[-20:]
    current_date = datetime.now(timezone.utc).isoformat()
    return {
        **prev,
        "user_message":         text,
        "telegram_id":          user_id,
        "thread_id":            str(user_id),
        "current_date":         current_date,
        # ── reset all transient fields ──────────────────────────────────
        "intent":               None,
        "extracted_data":       None,
        "split_expenses":       None,
        "update_data":          None,
        "income_data":          None,
        "fixed_payment_data":   None,
        "pending_delete":       None,
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


async def run_test():
    print("Initializing DB and Graph...")
    await init_db()
    await init_graph(force_memory=True)

    app_graph  = workflow_module.app_graph
    user_id    = 12345
    config     = {"configurable": {"thread_id": str(user_id)}}

    # ── Turn 1: تسجيل مصروف بدون مبلغ ──────────────────────────────────────
    print("\n=== TURN 1: 'اشتريت قهوة' ===")
    p1 = (await app_graph.aget_state(config)).values if await app_graph.aget_state(config) else {}
    r1 = await app_graph.ainvoke(_make_state(p1, "اشتريت قهوة", user_id), config=config)
    print("Bot:", r1.get("response"))

    # ── Turn 2: تقديم المبلغ ─────────────────────────────────────────────────
    print("\n=== TURN 2: '20 جنيه' ===")
    p2 = (await app_graph.aget_state(config)).values
    r2 = await app_graph.ainvoke(_make_state(p2, "20 جنيه", user_id), config=config)
    print("Bot:", r2.get("response"))

    # ── Turn 3: استعلام بالعربي ──────────────────────────────────────────────
    print("\n=== TURN 3: 'كام صرفت النهارده؟' ===")
    p3 = (await app_graph.aget_state(config)).values
    r3 = await app_graph.ainvoke(_make_state(p3, "كام صرفت النهارده؟", user_id), config=config)
    print("Bot:", r3.get("response"))
    print("Query Key:", r3.get("query_key"))

    # ── Turn 4: تسجيل دخل ───────────────────────────────────────────────────
    print("\n=== TURN 4: 'قبضت 5000 راتب' ===")
    p4 = (await app_graph.aget_state(config)).values
    r4 = await app_graph.ainvoke(_make_state(p4, "قبضت 5000 راتب", user_id), config=config)
    print("Bot:", r4.get("response"))
    print("Intent:", r4.get("intent"))

    # ── Turn 5: الرصيد ───────────────────────────────────────────────────────
    print("\n=== TURN 5: 'فضلي كام؟' ===")
    p5 = (await app_graph.aget_state(config)).values
    r5 = await app_graph.ainvoke(_make_state(p5, "فضلي كام؟", user_id), config=config)
    print("Bot:", r5.get("response"))

    # ── Turn 6: إضافة قسط ───────────────────────────────────────────────────
    print("\n=== TURN 6: 'عندي قسط سيارة 800 جنيه كل أول الشهر' ===")
    p6 = (await app_graph.aget_state(config)).values
    r6 = await app_graph.ainvoke(_make_state(p6, "عندي قسط سيارة 800 جنيه كل أول الشهر", user_id), config=config)
    print("Bot:", r6.get("response"))

    # ── Turn 7: مصروفين في رسالة ─────────────────────────────────────────────
    print("\n=== TURN 7: 'صرفت 2400 على أكل ومواصلات' ===")
    p7 = (await app_graph.aget_state(config)).values
    r7 = await app_graph.ainvoke(_make_state(p7, "صرفت 2400 على أكل ومواصلات", user_id), config=config)
    print("Bot:", r7.get("response"))
    print("Needs split:", r7.get("needs_clarification"))


if __name__ == "__main__":
    asyncio.run(run_test())
