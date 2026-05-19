import sys
import asyncio

# Windows: psycopg3 requires SelectorEventLoop (incompatible with ProactorEventLoop)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import codecs
from dotenv import load_dotenv

load_dotenv()

sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())

from app.database.connection import init_db
from app.graph.workflow import init_graph
import app.graph.workflow as workflow_module


async def run_test():
    print("Initializing DB and Graph...")
    await init_db()
    await init_graph(force_memory=True)  # MemorySaver for local testing

    app_graph = workflow_module.app_graph
    user_id = 12345
    config = {"configurable": {"thread_id": str(user_id)}}

    # ── Turn 1: Log expense without amount ──────────────────────────────────
    print("\n=== TURN 1: 'اشتريت قهوة' ===")
    text1 = "اشتريت قهوة"

    persisted1 = await app_graph.aget_state(config)
    prev1 = persisted1.values if persisted1 else {}

    state1 = {
        **prev1,
        "user_message": text1,
        "telegram_id": user_id,
        "thread_id": str(user_id),
        "current_date": "2026-05-19T07:00:00+00:00",
        "intent": None, "extracted_data": None, "split_expenses": None,
        "update_data": None, "query_key": None, "query_params": None,
        "sql_result": None, "needs_clarification": False,
        "clarification_question": None, "pending_confirmation": False,
        "confirmation_action": None, "operation_status": None,
        "response": None, "error": None,
        "conversation_history": prev1.get("conversation_history", [])[-20:],
    }

    result1 = await app_graph.ainvoke(state1, config=config)
    print("Bot Response 1:", result1.get("response"))
    print("History:", result1.get("conversation_history"))

    # ── Turn 2: Provide the amount ──────────────────────────────────────────
    print("\n=== TURN 2: '20 جنيه' ===")
    text2 = "20 جنيه"

    persisted2 = await app_graph.aget_state(config)
    prev2 = persisted2.values if persisted2 else {}

    state2 = {
        **prev2,
        "user_message": text2,
        "telegram_id": user_id,
        "thread_id": str(user_id),
        "current_date": "2026-05-19T07:00:00+00:00",
        "intent": None, "extracted_data": None, "split_expenses": None,
        "update_data": None, "query_key": None, "query_params": None,
        "sql_result": None, "needs_clarification": False,
        "clarification_question": None, "pending_confirmation": False,
        "confirmation_action": None, "operation_status": None,
        "response": None, "error": None,
        "conversation_history": prev2.get("conversation_history", [])[-20:],
    }

    result2 = await app_graph.ainvoke(state2, config=config)
    print("Bot Response 2:", result2.get("response"))
    print("History:", result2.get("conversation_history"))

    # ── Turn 3: Arabic date query ───────────────────────────────────────────
    print("\n=== TURN 3: 'كام صرفت النهارده؟' ===")
    text3 = "كام صرفت النهارده؟"

    persisted3 = await app_graph.aget_state(config)
    prev3 = persisted3.values if persisted3 else {}

    state3 = {
        **prev3,
        "user_message": text3,
        "telegram_id": user_id,
        "thread_id": str(user_id),
        "current_date": "2026-05-19T07:00:00+00:00",
        "intent": None, "extracted_data": None, "split_expenses": None,
        "update_data": None, "query_key": None, "query_params": None,
        "sql_result": None, "needs_clarification": False,
        "clarification_question": None, "pending_confirmation": False,
        "confirmation_action": None, "operation_status": None,
        "response": None, "error": None,
        "conversation_history": prev3.get("conversation_history", [])[-20:],
    }

    result3 = await app_graph.ainvoke(state3, config=config)
    print("Bot Response 3:", result3.get("response"))
    print("Query Key:", result3.get("query_key"))


if __name__ == "__main__":
    asyncio.run(run_test())
