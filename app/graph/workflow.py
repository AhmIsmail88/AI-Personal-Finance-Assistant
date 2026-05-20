import asyncio
import sys
import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command
from app.graph.state import AgentState
from app.agents.router import route_request
from app.agents.extractor import extract_data
from app.agents.db_agent import execute_operation
from app.agents.analyst import summarize_response
from app.config import settings

# Windows requires SelectorEventLoop for psycopg
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logger = logging.getLogger(__name__)

# Module-level reference — populated by init_graph() at server startup
app_graph = None


def _build_workflow() -> StateGraph:
    """Constructs the StateGraph workflow (without checkpointer — added on compile)."""
    workflow = StateGraph(AgentState)

    # ── Nodes ─────────────────────────────────────────────────────────────────
    workflow.add_node("router", route_request)
    workflow.add_node("extractor", extract_data)
    workflow.add_node("db_agent", execute_operation)
    workflow.add_node("analyst", summarize_response)

    # Fix #1: confirm_delete يرجع pending_delete في الـ state
    # confirmed = True  → المستخدم وافق → pending_delete=True → db_agent يحذف
    # confirmed = False → المستخدم رفض  → pending_delete=False → db_agent يتجاهل
    def confirm_delete(state: AgentState):
        confirmed = interrupt("confirm_delete")
        if confirmed:
            return {**state, "pending_delete": True,  "pending_confirmation": False}
        return     {**state, "pending_delete": False, "pending_confirmation": False}

    workflow.add_node("confirm_delete", confirm_delete)

    # ── Entry point ───────────────────────────────────────────────────────────
    workflow.set_entry_point("router")

    # ── Routing after router ──────────────────────────────────────────────────
    def route_decision(state: AgentState):
        if state.get("needs_clarification"):
            return "analyst"

        intent = state.get("intent")
        if intent == "log_expense":
            return "extractor"
        elif intent == "query_finance":
            return "db_agent"
        elif intent == "delete_entry":
            return "confirm_delete"
        elif intent == "update_expense":
            return "extractor"
        elif intent == "export_report":
            return "db_agent"
        elif intent == "log_income":
            return "extractor"
        elif intent == "query_balance":
            return "db_agent"
        elif intent == "add_fixed_payment":
            return "extractor"
        elif intent == "list_fixed_payments":
            return "db_agent"
        else:
            return "analyst"

    workflow.add_conditional_edges(
        "router",
        route_decision,
        {
            "extractor":      "extractor",
            "db_agent":       "db_agent",
            "confirm_delete": "confirm_delete",
            "analyst":        "analyst",
        }
    )

    # ── After extraction ──────────────────────────────────────────────────────
    def after_extractor(state: AgentState):
        if state.get("needs_clarification"):
            return "analyst"
        return "db_agent"

    workflow.add_conditional_edges(
        "extractor",
        after_extractor,
        {"db_agent": "db_agent", "analyst": "analyst"}
    )

    workflow.add_edge("confirm_delete", "db_agent")
    workflow.add_edge("db_agent", "analyst")
    workflow.add_edge("analyst", END)

    return workflow


async def init_graph(force_memory: bool = False):
    """
    Initialize the graph with AsyncPostgresSaver (production) or MemorySaver (dev/test).
    Must be called inside a running asyncio event loop.
    """
    global app_graph

    if force_memory:
        workflow = _build_workflow()
        app_graph = workflow.compile(checkpointer=MemorySaver())
        logger.info("Graph initialized with MemorySaver (forced).")
        return

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool
        from psycopg import AsyncConnection

        pg_url = settings.postgres_url.replace("postgresql+asyncpg://", "postgresql://")

        # Step 1: setup() via direct connection (bypasses PgBouncer)
        try:
            async with await AsyncConnection.connect(
                pg_url, autocommit=True, prepare_threshold=0
            ) as direct_conn:
                direct_checkpointer = AsyncPostgresSaver(direct_conn)
                await direct_checkpointer.setup()
                logger.info("Checkpointer tables set up via direct connection.")
        except Exception as setup_err:
            logger.warning(
                f"checkpointer.setup() failed ({setup_err}). "
                "Tables may already exist — continuing."
            )

        # Step 2: pool for normal checkpointing
        pool = AsyncConnectionPool(
            conninfo=pg_url,
            max_size=5,
            kwargs={"prepare_threshold": 0},
            open=False,
        )
        await pool.open()

        checkpointer = AsyncPostgresSaver(pool)
        workflow = _build_workflow()
        app_graph = workflow.compile(checkpointer=checkpointer)
        logger.info("Graph initialized with AsyncPostgresSaver.")

    except Exception as e:
        logger.warning(f"AsyncPostgresSaver init failed ({e}), falling back to MemorySaver.")
        workflow = _build_workflow()
        app_graph = workflow.compile(checkpointer=MemorySaver())
        logger.info("Graph initialized with MemorySaver (fallback).")
