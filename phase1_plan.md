# AI Personal Finance Assistant — Phase 1 Plan

## Bug Report + خطة التعديلات المرحلة الأولى

---

## أولاً: Bug Report

### 🔴 Bug #1 — Delete Logic معكوسة تماماً
**الملف:** `app/agents/db_agent.py`

**المشكلة:**
```python
# الكود الحالي — منطق معكوس
if not state.get("pending_confirmation", True):
```
`pending_confirmation` بيبدأ بـ `False` في كل message جديدة.
- `not False = True` → الحذف بيتنفذ فوراً بدون confirmation ❌
- لو بقى `True` → `not True = False` → مش بيحذف خالص ❌

**الإصلاح:**
```python
if state.get("pending_confirmation") == False:
```

---

### 🔴 Bug #2 — Delete Flow معطل من الأساس
**الملف:** `app/graph/workflow.py`

**المشكلة:**
```python
def confirm_delete(state: AgentState):
    if state.get("pending_confirmation"):  # ← دايماً False في البداية
        confirm = interrupt(...)           # ← مش بيحصل خالص
    return state                           # ← بيعدي عليه بدون توقف
```
الـ `interrupt()` مش بيتنفذ لأن `pending_confirmation` بيبدأ بـ `False` دايماً.

**الإصلاح:**
```python
def confirm_delete(state: AgentState):
    # دايماً interrupt عشان نتأكد من المستخدم
    confirm = interrupt("confirm_delete")
    return {**state, "pending_confirmation": not confirm}
```

---

### 🔴 Bug #3 — أزرار Yes/No مش بتظهر للمستخدم
**الملف:** `app/interface/telegram_handler.py`

**المشكلة:**
```python
elif result.get("intent") == "delete_entry" and result.get("response") is None:
    # هذا الشرط لا يتحقق أبداً لأن:
    # ١. الـ graph مش بيتوقف (Bug #2)
    # ٢. الـ analyst دايماً بيرجع response
```
المستخدم بيشوف رسالة بدل أزرار الـ Yes/No.

**الإصلاح:** إصلاح Bug #2 أولاً + استخدام `GraphInterrupt` exception للكشف عن الـ interrupt.

---

### 🔴 Bug #4 — البوت مش بيفهم العربية
**الملف:** `app/agents/db_agent.py`

**المشكلة:**
```python
# _select_query بتتحقق من كلمات إنجليزية بس
if any(k in msg for k in ["today"]):
if any(k in msg for k in ["this week", "week"]):
if any(k in msg for k in ["this month", "month"]):
```
لو المستخدم كتب "النهارده" أو "امس" أو "الأسبوع ده" → مش بيتعرف → يرجع `recent_expenses` بشكل خاطئ.

**الإصلاح:** إضافة الكلمات العربية لكل keyword list + إنشاء `date_resolver.py`.

---

### 🟡 Bug #5 — Context المحادثة بيتبعت بشكل غريب للـ LLM
**الملف:** `app/agents/extractor.py`

**المشكلة:**
```python
history = "\n".join(str(m) for m in state.get("conversation_history", []))
# str() على tuple بيرجع: "('user', 'الرسالة')"
# الـ LLM بيشوف نص تقني مش محادثة طبيعية
```

**الإصلاح:**
```python
history = "\n".join(
    f"{role}: {msg}" 
    for role, msg in state.get("conversation_history", [])
)
```

---

### 🟡 Bug #6 — DateTime بدون Timezone
**الملف:** `app/database/models.py`

**المشكلة:**
```python
created_at = Column(DateTime, default=datetime.utcnow)
# DateTime بدون timezone=True
# لكن في connection.py الجداول اتعملت بـ TIMESTAMPTZ
# تعارض بين ORM و DB → مشاكل في date comparisons مستقبلاً
```

**الإصلاح:**
```python
from sqlalchemy import DateTime
from datetime import timezone

created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

---

### 🟡 Bug #7 — `total_by_category` بيقطع البيانات خفية
**الملف:** `app/agents/db_agent.py`

**المشكلة:**
```python
"since": datetime.utcnow() - timedelta(days=30)
# المستخدم بيسأل عن "breakdown" من غير تحديد فترة
# البيانات الأقدم من 30 يوم بتتقطع بدون ما يعرف
```

**الإصلاح:** إضافة query منفصلة `total_by_category_alltime` للحالات اللي مفيهاش date range محدد.

---

### 🟠 Bug #8 — `update_expense` مش موجود في Analyst
**الملف:** `app/agents/analyst.py`

**المشكلة:**
```python
# مفيش handling لـ update_expense intent
# لو اتضاف في router → analyst هيرجع:
msg = "No data found for that request."  # رد غلط على update ناجح
```

**الإصلاح:** إضافة branch جديدة في `analyst.py` لـ `update_expense`.

---

### 🟠 Bug #9 — MemorySaver في Production
**الملف:** `app/graph/workflow.py`

**المشكلة:**
```python
checkpointer = MemorySaver()
# الذاكرة في RAM بس
# أي restart للسيرفر → كل المحادثات بتضيع
```

**الإصلاح:** استبدال بـ `AsyncPostgresSaver`.

---

### ⚠️ تحذير — History بتتضاف مرتين (محتمل)
**الملف:** `app/agents/router.py`

```python
history = history + [("user", state["user_message"])]
# الـ router بيضيف user message
# لو في أي وقت اتضافت في telegram_handler برضه → ازدواجية
```
محتاج مراجعة عند إضافة sliding window.

---

### ⚠️ تحذير — Amount ممكن تكون سالبة
**الملف:** `app/agents/extractor.py`

```python
amount: float | None
# مفيش validation على القيمة
# المستخدم يقدر يسجل "-500 EGP" وهتتحفظ في DB
```

---

## ثانياً: خطة التعديلات — المرحلة الأولى

---

### الملفات اللي هتتعدل

---

#### 📄 `app/graph/state.py`
**الإضافات:**
- `current_date: str | None` — التاريخ الحالي بيتحقن من `telegram_handler`
- `split_expenses: list[dict] | None` — لتسجيل أكتر من expense في رسالة واحدة
- `update_data: dict | None` — بيانات الـ update

```python
# إضافة للـ AgentState:
current_date: str | None
split_expenses: list[dict] | None
update_data: dict | None
```

---

#### 📄 `app/interface/telegram_handler.py`
**التعديلات:**
1. حقن `current_date` في الـ initial state
2. Sliding window — آخر 20 رسالة بس
3. إصلاح منطق الـ delete keyboard (Bug #3)

```python
from datetime import datetime, timezone

# في handle_message:
current_date = datetime.now(timezone.utc).isoformat()

# Sliding window:
history = prev_values.get("conversation_history", [])
history = history[-20:]  # آخر 20 رسالة بس

initial_state = {
    **prev_values,
    "current_date": current_date,
    "conversation_history": history,
    ...
}

# إصلاح delete detection:
try:
    result = await app_graph.ainvoke(initial_state, config=config)
    ...
except GraphInterrupt:
    # إظهار أزرار Yes/No
    keyboard = [[
        InlineKeyboardButton("✅ نعم، احذف", callback_data="delete_confirm"),
        InlineKeyboardButton("❌ لأ، احتفظ", callback_data="delete_cancel"),
    ]]
    await update.message.reply_text(
        "هل أنت متأكد من حذف آخر مصروف؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
```

---

#### 📄 `app/agents/router.py`
**التعديلات:**
1. إضافة `update_expense` intent
2. إضافة `export_report` intent

```python
class RouterOutput(BaseModel):
    intent: Literal[
        "log_expense",
        "query_finance", 
        "delete_entry",
        "update_expense",   # ← جديد
        "export_report",    # ← جديد
        "unknown"
    ]
```

**System prompt إضافة:**
```
5. update_expense — تعديل مصروف موجود ("عدل آخر مصروف", "غير الكاتيجوري")
6. export_report  — تصدير تقرير ("طلعلي إكسيل", "export شهري")
```

---

#### 📄 `app/agents/extractor.py`
**التعديلات:**
1. إصلاح Bug #5 — history formatting
2. إضافة amount validation (مش سالبة)
3. منطق Split Categories — لو في أكتر من category في رسالة واحدة

```python
# إصلاح history:
history = "\n".join(
    f"{role}: {msg}" 
    for role, msg in state.get("conversation_history", [])
)

# إضافة MultiExpenseSchema:
class MultiExpenseSchema(BaseModel):
    expenses: list[ExpenseSchema]
    needs_split_clarification: bool
    clarification_question: str | None

# المنطق الجديد:
# ١. لو في كلمتين من categories مختلفة + مبلغ واحد
#    → needs_split_clarification = True
#    → "كام صرفت على الأكل؟ وكام على المواصلات؟"
# ٢. لو المستخدم جاوب بتقسيم واضح
#    → split_expenses = [{"item":..., "amount":..., "category":...}, ...]
```

---

#### 📄 `app/agents/db_agent.py`
**التعديلات:**

**١. إصلاح Bug #1:**
```python
if state.get("pending_confirmation") == False:  # إصلاح المنطق المعكوس
```

**٢. إضافة keywords عربية:**
```python
ARABIC_TODAY = ["النهارده", "اليوم", "today"]
ARABIC_YESTERDAY = ["امس", "أمس", "yesterday"]
ARABIC_WEEK = ["الأسبوع ده", "هذا الأسبوع", "this week", "week"]
ARABIC_MONTH = ["الشهر ده", "هذا الشهر", "this month", "month"]
```

**٣. Query Templates جديدة:**
```sql
-- امس
"total_yesterday": WHERE DATE(created_at) = :target_date

-- تاريخ محدد
"total_specific_date": WHERE DATE(created_at) = :target_date

-- أسبوعي
"report_weekly": GROUP BY DATE(created_at) للأسبوع الحالي

-- شهري تفصيلي
"report_monthly_detail": breakdown by category للشهر

-- نصف سنوي
"report_half_year": آخر 6 شهور GROUP BY month

-- سنوي
"report_yearly": آخر 12 شهر GROUP BY month

-- Category alltime (بدون date filter)
"total_by_category_alltime": بدون :since
```

**٤. إضافة update logic:**
```python
elif state.get("intent") == "update_expense":
    data = state.get("update_data")
    # UPDATE expenses SET ... WHERE id = last OR specific condition
```

**٥. إضافة split expenses logic:**
```python
elif state.get("split_expenses"):
    for expense in state["split_expenses"]:
        # insert كل expense لوحده
```

**٦. إصلاح Bug #7 — category alltime:**
```python
if any(k in msg for k in ["category", "breakdown"]) and no_date_mentioned:
    return "total_by_category_alltime", {"user_id": user_id}
```

---

#### 📄 `app/agents/analyst.py`
**التعديلات:**
1. إضافة handling لـ `update_expense`
2. إضافة handling لـ `export_report`
3. إضافة handling لـ `split_expenses` (رد بعد تسجيل أكتر من expense)

```python
# إضافة في الـ intent handling:
elif intent == "update_expense" and status == "success":
    human_text = "تم تحديث المصروف بنجاح. اكتب رسالة تأكيد ودية."

elif intent == "export_report" and status == "success":
    # الـ analyst مش بيبعت رسالة — الـ excel_exporter بيبعت الملف
    return {**state, "response": None}

elif state.get("split_expenses") and status == "success":
    human_text = f"تم تسجيل {len(state['split_expenses'])} مصاريف. اكتب تأكيد ودي."
```

---

#### 📄 `app/graph/workflow.py`
**التعديلات:**
1. إصلاح Bug #2 — confirm_delete
2. استبدال `MemorySaver` بـ `AsyncPostgresSaver`
3. إضافة edges للـ intents الجديدة

```python
# إصلاح confirm_delete:
def confirm_delete(state: AgentState):
    interrupt("confirm_delete")  # دايماً بيوقف
    return state

# AsyncPostgresSaver:
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

async def build_graph():
    async with AsyncPostgresSaver.from_conn_string(settings.postgres_url) as checkpointer:
        await checkpointer.setup()
        workflow = StateGraph(AgentState)
        ...
        return workflow.compile(checkpointer=checkpointer)

# Edges جديدة:
def route_decision(state: AgentState):
    ...
    elif intent == "update_expense":
        return "extractor"    # عشان يستخرج بيانات الـ update
    elif intent == "export_report":
        return "db_agent"     # يجيب البيانات الأول
```

---

#### 📄 `app/database/models.py`
**التعديل:**
```python
# إصلاح Bug #6:
from datetime import timezone
created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

---

### الملفات الجديدة

---

#### 📄 `app/agents/date_resolver.py` *(جديد)*
**الغرض:** حساب كل التواريخ من `current_date` في Python — مش من LLM ومش من DB.

```python
from datetime import datetime, timedelta, timezone
from app.graph.state import AgentState

def resolve_date_params(query_key: str, current_date: datetime) -> dict:
    today = current_date.date()
    
    mapping = {
        "total_today":      {"target_date": today},
        "total_yesterday":  {"target_date": today - timedelta(days=1)},
        "total_this_week":  {"since": today - timedelta(days=today.weekday())},
        "total_this_month": {"since": today.replace(day=1)},
        "report_half_year": {"since": today - timedelta(days=182)},
        "report_yearly":    {"since": today - timedelta(days=365)},
    }
    return mapping.get(query_key, {})

def detect_date_intent(user_message: str, current_date: datetime) -> str | None:
    """
    بيكشف الـ query_key المناسب من الرسالة
    بيدعم العربي والإنجليزي
    """
    msg = user_message.lower()
    
    today_kw    = ["النهارده", "اليوم", "today", "اليوم ده"]
    yesterday_kw = ["امس", "أمس", "yesterday", "البارح"]
    week_kw     = ["الأسبوع", "أسبوع", "this week", "week"]
    month_kw    = ["الشهر", "شهر", "this month", "month"]
    half_year_kw = ["نصف سنة", "6 شهور", "ستة شهور", "half year"]
    yearly_kw   = ["سنة", "سنوي", "yearly", "annual", "year"]
    
    if any(k in msg for k in yesterday_kw): return "total_yesterday"
    if any(k in msg for k in today_kw):     return "total_today"
    if any(k in msg for k in yearly_kw):    return "report_yearly"
    if any(k in msg for k in half_year_kw): return "report_half_year"
    if any(k in msg for k in month_kw):     return "total_this_month"
    if any(k in msg for k in week_kw):      return "total_this_week"
    
    return None
```

---

#### 📄 `app/agents/excel_exporter.py` *(جديد)*
**الغرض:** توليد تقرير Excel احترافي وبعته عبر Telegram.

```python
import io
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.chart import BarChart, Reference
from telegram import Bot
from app.graph.state import AgentState

async def export_excel_report(state: AgentState, bot: Bot, chat_id: int) -> AgentState:
    """
    يولد Excel بـ 3 sheets:
    - Summary: إجمالي per category
    - Transactions: كل المصاريف
    - Chart: Bar chart تلقائي
    """
    sql_result = state.get("sql_result", [])
    
    wb = openpyxl.Workbook()
    
    # Sheet 1: Summary
    ws_summary = wb.active
    ws_summary.title = "Summary"
    # Headers بـ styling
    headers = ["Category", "Total (EGP)", "Count", "Average"]
    for col, header in enumerate(headers, 1):
        cell = ws_summary.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2E86AB")
    
    # Sheet 2: Transactions
    ws_trans = wb.create_sheet("Transactions")
    
    # Sheet 3: Chart
    ws_chart = wb.create_sheet("Chart")
    chart = BarChart()
    chart.title = "Spending by Category"
    # ... chart setup
    
    # حفظ في memory buffer
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    
    # بعت الملف على Telegram
    report_name = f"finance_report_{state.get('current_date', 'report')[:10]}.xlsx"
    await bot.send_document(
        chat_id=chat_id,
        document=buffer,
        filename=report_name,
        caption="📊 تقريرك المالي جاهز!"
    )
    
    return {**state, "operation_status": "success"}
```

---

## ثالثاً: ترتيب التنفيذ

```
الخطوة ١ — إصلاح Bugs الحرجة
├── Bug #1: db_agent.py — pending_confirmation logic
├── Bug #2: workflow.py — confirm_delete + interrupt
├── Bug #3: telegram_handler.py — delete keyboard
└── Bug #5: extractor.py — history formatting

الخطوة ٢ — ملفات جديدة
├── date_resolver.py
└── state.py (إضافة fields)

الخطوة ٣ — التاريخ والعربية
├── telegram_handler.py — حقن current_date
├── db_agent.py — keywords عربية + templates جديدة
└── db_agent.py — استخدام date_resolver

الخطوة ٤ — الذاكرة
├── workflow.py — AsyncPostgresSaver
└── telegram_handler.py — sliding window 20

الخطوة ٥ — Intents جديدة
├── router.py — update_expense + export_report
├── extractor.py — split categories
├── db_agent.py — update logic + split insert
└── analyst.py — ردود جديدة

الخطوة ٦ — Excel Export
└── excel_exporter.py

الخطوة ٧ — Bug Fixes المتبقية
├── Bug #6: models.py — DateTime timezone
└── Bug #7: db_agent.py — category alltime query
```

---

## رابعاً: ملخص الملفات

| الملف | نوع التعديل | الأولوية |
|---|---|---|
| `app/agents/db_agent.py` | تعديل كبير | 🔴 حرج |
| `app/graph/workflow.py` | تعديل كبير | 🔴 حرج |
| `app/interface/telegram_handler.py` | تعديل متوسط | 🔴 حرج |
| `app/agents/extractor.py` | تعديل متوسط | 🟡 مهم |
| `app/agents/router.py` | تعديل بسيط | 🟡 مهم |
| `app/agents/analyst.py` | تعديل بسيط | 🟡 مهم |
| `app/graph/state.py` | إضافة fields | 🟡 مهم |
| `app/database/models.py` | تعديل بسيط | 🟠 متوسط |
| `app/agents/date_resolver.py` | **جديد** | 🔴 حرج |
| `app/agents/excel_exporter.py` | **جديد** | 🟠 متوسط |
