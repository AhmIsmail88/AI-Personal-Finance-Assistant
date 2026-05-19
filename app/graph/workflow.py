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

# Windows requires SelectorEventLoop for psycopg (psycopg3 is incompatible with ProactorEventLoop)
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

    # Bug #2 fix: confirm_delete ALWAYS interrupts (never checks a flag first)
    def confirm_delete(state: AgentState):
        # Pauses the graph — resumes via Command(resume=True/False) from telegram_handler
        confirmed = interrupt("confirm_delete")
        if confirmed:
            # User confirmed → set flag so db_agent knows to proceed with deletion
            return {**state, "pending_delete": True, "pending_confirmation": False}
        # User cancelled → flag stays False, db_agent skips deletion
        return {**state, "pending_delete": False, "pending_confirmation": False}

    workflow.add_node("confirm_delete", confirm_delete)

    # ── Entry point ───────────────────────────────────────────────────────────
    workflow.set_entry_point("router")

    # ── Routing after router ──────────────────────────────────────────────────
    def route_decision(state: AgentState):
        if state.get("needs_clarification"):
            return "analyst"  # let analyst surface the clarification question

        intent = state.get("intent")
        if intent == "log_expense":
            return "extractor"
        elif intent == "query_finance":
            return "db_agent"
        elif intent == "delete_entry":
            return "confirm_delete"
        elif intent == "update_expense":
            return "extractor"   # extractor pulls update_data fields
        elif intent == "export_report":
            return "db_agent"    # db_agent fetches the data, handler sends the file
        else:
            return "analyst"     # unknown → analyst gives a polite redirect

    workflow.add_conditional_edges(
        "router",
        route_decision,
        {
            "extractor": "extractor",
            "db_agent": "db_agent",
            "confirm_delete": "confirm_delete",
            "analyst": "analyst",
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
    Initialize the graph with AsyncPostgresSaver checkpointer (production)
    or MemorySaver (dev/testing).

    Args:
        force_memory: If True, skip Postgres and use MemorySaver. Use this
                      in tests or when Postgres is unavailable.

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

        # Convert asyncpg URL to psycopg URL
        pg_url = settings.postgres_url.replace(
            "postgresql+asyncpg://", "postgresql://"
        )

        # ── Step 1: Run setup() via direct connection ─────────────────────────
        # PgBouncer in transaction mode doesn't support CREATE INDEX CONCURRENTLY.
        # We use a direct connection (bypass PgBouncer) for the setup only.
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

        # ── Step 2: Build pool for normal checkpointing ───────────────────────
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
        logger.warning(
            f"AsyncPostgresSaver init failed ({e}), falling back to MemorySaver."
        )
        workflow = _build_workflow()
        app_graph = workflow.compile(checkpointer=MemorySaver())
        logger.info("Graph initialized with MemorySaver (fallback).")



