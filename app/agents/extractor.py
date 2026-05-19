from typing import Literal
from pydantic import BaseModel, Field, field_validator
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from app.config import settings
from app.graph.state import AgentState

CATEGORIES = [
    "Food", "Transport", "Utilities", "Entertainment",
    "Electronics", "Health", "Education", "Shopping", "Housing", "Other"
]

# ── Schemas ────────────────────────────────────────────────────────────────

class ExpenseSchema(BaseModel):
    item: str = Field(description="The item or service purchased")
    amount: float | None = Field(
        default=None,
        description="Numeric cost as float, e.g. 80.0. Null if not mentioned."
    )
    currency: str = Field(default="EGP", description="Currency code. Default EGP.")
    category: Literal[
        "Food", "Transport", "Utilities", "Entertainment",
        "Electronics", "Health", "Education", "Shopping", "Housing", "Other"
    ]

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError("Amount must be a positive number.")
        return v


class MultiExpenseSchema(BaseModel):
    """Used when the user might be logging more than one expense at once."""
    expenses: list[ExpenseSchema] = Field(
        description="List of extracted expenses. May be just one."
    )
    needs_split_clarification: bool = Field(
        default=False,
        description=(
            "True if the user mentioned multiple categories but a single total amount "
            "and we need to ask how to split it."
        )
    )
    clarification_question: str | None = Field(
        default=None,
        description="The question to ask the user about splitting, if needed."
    )


class UpdateExpenseSchema(BaseModel):
    """Extracted fields the user wants to update on their last expense."""
    new_amount: float | None = Field(
        default=None,
        description="New amount to set, or null if not changing the amount."
    )
    new_category: Literal[
        "Food", "Transport", "Utilities", "Entertainment",
        "Electronics", "Health", "Education", "Shopping", "Housing", "Other"
    ] | None = Field(
        default=None,
        description="New category to set, or null if not changing the category."
    )
    new_item: str | None = Field(
        default=None,
        description="New item description to set, or null if not changing it."
    )

    @field_validator("new_amount")
    @classmethod
    def amount_must_be_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError("Amount must be a positive number.")
        return v


class IncomeSchema(BaseModel):
    """Extracted income entry."""
    source_type: Literal["salary", "freelance", "part_time", "other"] = Field(
        description=(
            "Type of income source. "
            "salary=راتب شهري ثابت, freelance=فريلانس, part_time=بارت تايم, other=أخرى"
        )
    )
    description: str | None = Field(
        default=None,
        description="Brief description of the income source, e.g. 'شغل بارت تايم', 'مشروع فريلانس'"
    )
    amount: float | None = Field(
        default=None,
        description="Amount received. Null if not mentioned."
    )
    currency: str = Field(default="EGP", description="Currency code. Default EGP.")

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError("Amount must be positive.")
        return v


class FixedPaymentSchema(BaseModel):
    """Extracted recurring bill or installment."""
    name: str = Field(description="Name of the bill/installment, e.g. 'إيجار', 'قسط سيارة'")
    amount: float | None = Field(
        default=None,
        description="Monthly amount. Null if not mentioned."
    )
    currency: str = Field(default="EGP")
    category: Literal["rent", "loan", "utility", "subscription", "other"] = Field(
        description=(
            "Category: rent=إيجار, loan=قرض/قسط, "
            "utility=فاتورة كهرباء/مياه/غاز, subscription=اشتراك, other=أخرى"
        )
    )
    due_day: int | None = Field(
        default=None,
        description="Day of month the payment is due (1-31). Null if not mentioned."
    )
    remind_days_before: int = Field(
        default=3,
        description="How many days before due_day to send a reminder. Default 3."
    )


# ── System prompts ─────────────────────────────────────────────────────────

EXTRACT_SYSTEM = f"""You are a financial data extraction expert. Extract expense info and respond ONLY with valid JSON.

Rules:
- item: what was bought (e.g. "pizza", "taxi", "electricity")
- amount: float or null (only null if truly not mentioned)
- currency: e.g. EGP, USD. Default "EGP"
- category: MUST be exactly one of: {", ".join(CATEGORIES)}
  Examples: pizza→Food, taxi→Transport, rent→Housing, electricity→Utilities,
  phone→Electronics, doctor→Health, book→Education, clothes→Shopping

- If the user mentions multiple different items/categories, return multiple expenses in the list.
- If the user mentions multiple categories but only one total amount (ambiguous split),
  set needs_split_clarification=true and ask how they want to split it.
- All amounts must be positive numbers.

Return ONLY this JSON, nothing else:
{{"expenses": [{{"item": "...", "amount": 80.0, "currency": "EGP", "category": "Food"}}], "needs_split_clarification": false, "clarification_question": null}}"""


INCOME_SYSTEM = """You are a financial data extraction expert. The user is logging income they received.
Extract the income details and respond ONLY with valid JSON.

source_type must be exactly one of:
- salary      → راتب شهري ثابت, monthly salary
- freelance   → فريلانس, مشروع, project
- part_time   → بارت تايم, شغل جانبي
- other       → أي مصدر تاني

Return ONLY this JSON:
{"source_type": "salary", "description": "...", "amount": 5000.0, "currency": "EGP"}"""


FIXED_PAYMENT_SYSTEM = """You are a financial data extraction expert. The user is adding a recurring monthly bill or installment.
Extract the details and respond ONLY with valid JSON.

category must be exactly one of:
- rent         → إيجار
- loan         → قرض, قسط سيارة, قسط بنك
- utility      → كهرباء, مياه, غاز, إنترنت, تليفون
- subscription → اشتراك, Netflix, Spotify
- other        → أي حاجة تانية

Return ONLY this JSON:
{"name": "إيجار", "amount": 2000.0, "currency": "EGP", "category": "rent", "due_day": 1, "remind_days_before": 3}"""


UPDATE_SYSTEM = f"""You are a financial data extraction expert.
Extract what they want to change and respond ONLY with valid JSON.

Fields they might want to change:
- new_amount: the new amount (positive float), or null if not changing
- new_category: must be one of: {", ".join(CATEGORIES)}, or null if not changing
- new_item: the new item name/description, or null if not changing

Return ONLY this JSON:
{{"new_amount": null, "new_category": "Food", "new_item": null}}"""


# ── Main extraction function ───────────────────────────────────────────────

async def extract_data(state: AgentState) -> AgentState:
    intent = state.get("intent")

    # Bug #5 fix: format history as "role: content" not str(tuple)
    history = "\n".join(
        f"{role}: {msg}"
        for role, msg in state.get("conversation_history", [])
    )

    llm = ChatOpenAI(
        model=settings.extractor_model,
        api_key=settings.groq_api_key,
        base_url=settings.groq_base_url,
        temperature=0.0,
        max_tokens=400,
    )

    # ── Income extraction ────────────────────────────────────────────────
    if intent == "log_income":
        try:
            structured_llm = llm.with_structured_output(IncomeSchema, method="json_mode")
            data: IncomeSchema = await structured_llm.ainvoke([
                SystemMessage(content=INCOME_SYSTEM),
                HumanMessage(
                    content=f"Conversation context:\n{history}\n\nUser message: {state['user_message']}"
                )
            ])
            if data.amount is None:
                return {
                    **state,
                    "needs_clarification": True,
                    "clarification_question": "كام المبلغ اللي استلمته؟ 💰",
                }
            return {
                **state,
                "income_data": data.model_dump(),
                "needs_clarification": False,
                "clarification_question": None,
            }
        except Exception as e:
            print(f"Income extractor error: {e}")
            return {
                **state,
                "error": str(e),
                "needs_clarification": True,
                "clarification_question": "مش فاهم. جرب: 'قبضت 5000 راتب' أو 'استلمت 1200 فريلانس'",
            }

    # ── Fixed payment extraction ─────────────────────────────────────────
    if intent == "add_fixed_payment":
        try:
            structured_llm = llm.with_structured_output(FixedPaymentSchema, method="json_mode")
            data: FixedPaymentSchema = await structured_llm.ainvoke([
                SystemMessage(content=FIXED_PAYMENT_SYSTEM),
                HumanMessage(
                    content=f"Conversation context:\n{history}\n\nUser message: {state['user_message']}"
                )
            ])
            if data.amount is None:
                return {
                    **state,
                    "fixed_payment_data": data.model_dump(),
                    "needs_clarification": True,
                    "clarification_question": f"كام مبلغ {data.name}؟ 💳",
                }
            if data.due_day is None:
                return {
                    **state,
                    "fixed_payment_data": data.model_dump(),
                    "needs_clarification": True,
                    "clarification_question": f"في أنهي يوم من الشهر بيستحق {data.name}؟ 📅",
                }
            return {
                **state,
                "fixed_payment_data": data.model_dump(),
                "needs_clarification": False,
                "clarification_question": None,
            }
        except Exception as e:
            print(f"Fixed payment extractor error: {e}")
            return {
                **state,
                "error": str(e),
                "needs_clarification": True,
                "clarification_question": "مش فاهم. جرب: 'عندي قسط سيارة 800 جنيه كل أول الشهر'",
            }

    # ── Update expense extraction ────────────────────────────────────────
    if intent == "update_expense":
        try:
            structured_llm = llm.with_structured_output(UpdateExpenseSchema, method="json_mode")
            data: UpdateExpenseSchema = await structured_llm.ainvoke([
                SystemMessage(content=UPDATE_SYSTEM),
                HumanMessage(
                    content=f"Conversation context:\n{history}\n\nUser message: {state['user_message']}"
                )
            ])

            # Nothing useful was extracted
            if not any([data.new_amount, data.new_category, data.new_item]):
                return {
                    **state,
                    "needs_clarification": True,
                    "clarification_question": (
                        "ماذا تريد تعديله في آخر مصروف؟ "
                        "يمكنك تغيير المبلغ، الفئة، أو الوصف. 🖊️"
                    ),
                }

            return {
                **state,
                "update_data": data.model_dump(exclude_none=True),
                "needs_clarification": False,
                "clarification_question": None,
            }

        except Exception as e:
            print(f"Update extractor error: {e}")
            return {
                **state,
                "error": str(e),
                "needs_clarification": True,
                "clarification_question": "لم أفهم ماذا تريد تعديله. حاول مرة أخرى، مثلاً: 'غير المبلغ إلى 50'",
            }

    # ── Normal log_expense extraction (+ split) ──────────────────────────
    try:
        structured_llm = llm.with_structured_output(MultiExpenseSchema, method="json_mode")
        data: MultiExpenseSchema = await structured_llm.ainvoke([
            SystemMessage(content=EXTRACT_SYSTEM),
            HumanMessage(
                content=f"Conversation context:\n{history}\n\nUser message: {state['user_message']}"
            )
        ])

        # Needs clarification about how to split a shared amount
        if data.needs_split_clarification:
            question = data.clarification_question or (
                "ذكرت أكتر من فئة بمبلغ واحد. كم صرفت على كل فئة؟ 🤔"
            )
            return {
                **state,
                "needs_clarification": True,
                "clarification_question": question,
            }

        # Validate we got at least one expense
        if not data.expenses:
            return {
                **state,
                "needs_clarification": True,
                "clarification_question": "I couldn't understand the expense. Try: 'Spent 150 EGP on pizza'",
            }

        # Single expense — check if amount is missing
        if len(data.expenses) == 1:
            single = data.expenses[0]
            if single.amount is None:
                return {
                    **state,
                    "extracted_data": single.model_dump(),
                    "needs_clarification": True,
                    "clarification_question": f"كام صرفت على {single.item}؟ 💰",
                }
            return {
                **state,
                "extracted_data": single.model_dump(),
                "split_expenses": None,
                "needs_clarification": False,
                "clarification_question": None,
            }

        # Multiple expenses
        return {
            **state,
            "split_expenses": [e.model_dump() for e in data.expenses],
            "extracted_data": data.expenses[0].model_dump(),  # fallback ref
            "needs_clarification": False,
            "clarification_question": None,
        }

    except Exception as e:
        print(f"Extractor error: {e}")
        return {
            **state,
            "error": str(e),
            "needs_clarification": True,
            "clarification_question": "I couldn't parse that. Try: 'Spent 150 EGP on pizza'",
        }
