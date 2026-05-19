import io
import logging
from datetime import datetime, timezone
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.chart import PieChart, Reference
from openpyxl.utils import get_column_letter
from telegram import Bot

logger = logging.getLogger(__name__)

# Color palette
HEADER_FILL  = PatternFill("solid", fgColor="2E86AB")   # Blue
ACCENT_FILL  = PatternFill("solid", fgColor="F6F6F6")   # Light grey alternating row
TOTAL_FILL   = PatternFill("solid", fgColor="A8DADC")   # Teal for totals
INCOME_FILL  = PatternFill("solid", fgColor="D4EDDA")   # Light green for income totals
HEADER_FONT  = Font(bold=True, color="FFFFFF", size=11)
TITLE_FONT   = Font(bold=True, color="1D3557", size=13)
NORMAL_FONT  = Font(size=10)
CENTER       = Alignment(horizontal="center", vertical="center")
LEFT         = Alignment(horizontal="left", vertical="center")
THIN_BORDER  = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)


def _auto_width(ws):
    """Auto-fit column widths based on content."""
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max_len + 4, 40)


def _style_header_row(ws, row: int, num_cols: int):
    for col in range(1, num_cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
        cell.border = THIN_BORDER


def generate_excel_report(sql_result: dict, current_date: str | None = None) -> io.BytesIO:
    """
    Generates a professional Excel workbook from sql_result dict (expenses and income).
    Returns an in-memory BytesIO buffer ready to send.
    """
    wb = openpyxl.Workbook()
    expenses = sql_result.get("expenses", [])
    income = sql_result.get("income", [])

    # ── Sheet 1: Summary ─────────────────────────────────────────────────────
    ws_summary = wb.active
    ws_summary.title = "Summary"

    ws_summary.merge_cells("A1:D1")
    title_cell = ws_summary["A1"]
    title_cell.value = "💰 Finance Report — Summary"
    title_cell.font = TITLE_FONT
    title_cell.alignment = CENTER

    # --- Expenses Summary ---
    ws_summary.cell(row=3, column=1, value="📉 Expenses by Category").font = Font(bold=True, size=11)
    headers = ["Category", "Total (EGP)", "Transactions", "Average (EGP)"]
    for col, h in enumerate(headers, 1):
        ws_summary.cell(row=4, column=col, value=h)
    _style_header_row(ws_summary, 4, len(headers))

    category_totals: dict[str, dict] = {}
    for row in expenses:
        cat = row.get("category", "Other")
        if cat not in category_totals:
            category_totals[cat] = {"total": 0.0, "count": 0}
        category_totals[cat]["total"] += float(row.get("amount") or 0)
        category_totals[cat]["count"] += 1

    r = 5
    for cat, data in sorted(category_totals.items(), key=lambda x: -x[1]["total"]):
        avg = round(data["total"] / data["count"], 2) if data["count"] else 0
        values = [cat, round(data["total"], 2), data["count"], avg]
        for c, v in enumerate(values, 1):
            cell = ws_summary.cell(row=r, column=c, value=v)
            cell.border = THIN_BORDER
            cell.alignment = LEFT
            cell.font = NORMAL_FONT
            if r % 2 == 0:
                cell.fill = ACCENT_FILL
        r += 1

    # Expenses Grand Total
    grand_total_expenses = sum(d["total"] for d in category_totals.values())
    ws_summary.cell(row=r, column=1, value="TOTAL EXPENSES").font = Font(bold=True)
    ws_summary.cell(row=r, column=2, value=round(grand_total_expenses, 2)).font = Font(bold=True)
    for c in range(1, 5):
        ws_summary.cell(row=r, column=c).fill = TOTAL_FILL
        ws_summary.cell(row=r, column=c).border = THIN_BORDER
    
    r += 3 # spacing

    # --- Income Summary ---
    ws_summary.cell(row=r, column=1, value="📈 Income Summary").font = Font(bold=True, size=11)
    r += 1
    income_headers = ["Source Type", "Total (EGP)", "Transactions", "Average (EGP)"]
    for col, h in enumerate(income_headers, 1):
        ws_summary.cell(row=r, column=col, value=h)
    _style_header_row(ws_summary, r, len(income_headers))
    
    r += 1
    income_totals: dict[str, dict] = {}
    for row in income:
        source = row.get("item", "Other")
        if source not in income_totals:
            income_totals[source] = {"total": 0.0, "count": 0}
        income_totals[source]["total"] += float(row.get("amount") or 0)
        income_totals[source]["count"] += 1
        
    for source, data in sorted(income_totals.items(), key=lambda x: -x[1]["total"]):
        avg = round(data["total"] / data["count"], 2) if data["count"] else 0
        values = [source, round(data["total"], 2), data["count"], avg]
        for c, v in enumerate(values, 1):
            cell = ws_summary.cell(row=r, column=c, value=v)
            cell.border = THIN_BORDER
            cell.alignment = LEFT
            cell.font = NORMAL_FONT
            if r % 2 == 0:
                cell.fill = ACCENT_FILL
        r += 1

    # Income Grand Total
    grand_total_income = sum(d["total"] for d in income_totals.values())
    ws_summary.cell(row=r, column=1, value="TOTAL INCOME").font = Font(bold=True)
    ws_summary.cell(row=r, column=2, value=round(grand_total_income, 2)).font = Font(bold=True)
    for c in range(1, 5):
        ws_summary.cell(row=r, column=c).fill = INCOME_FILL
        ws_summary.cell(row=r, column=c).border = THIN_BORDER
    
    r += 2 # spacing
    # Net Balance
    ws_summary.cell(row=r, column=1, value="NET BALANCE").font = Font(bold=True, size=12)
    ws_summary.cell(row=r, column=2, value=round(grand_total_income - grand_total_expenses, 2)).font = Font(bold=True, size=12)

    _auto_width(ws_summary)

    # ── Sheet 2: Expenses ─────────────────────────────────────────────────────
    if expenses:
        ws_exp = wb.create_sheet("Expenses")
        ws_exp.merge_cells("A1:E1")
        ws_exp["A1"].value = "📉 Expenses Transactions"
        ws_exp["A1"].font = TITLE_FONT
        ws_exp["A1"].alignment = CENTER

        trans_headers = ["Date", "Item", "Category", "Amount (EGP)", "Currency"]
        for col, h in enumerate(trans_headers, 1):
            ws_exp.cell(row=2, column=col, value=h)
        _style_header_row(ws_exp, 2, len(trans_headers))

        for row_idx, row in enumerate(expenses, start=3):
            created_at = row.get("created_at")
            if hasattr(created_at, "strftime"):
                date_str = created_at.strftime("%Y-%m-%d %H:%M")
            else:
                date_str = str(created_at)[:16] if created_at else ""

            values = [
                date_str,
                row.get("item", ""),
                row.get("category", ""),
                float(row.get("amount") or 0),
                row.get("currency", "EGP"),
            ]
            for c, v in enumerate(values, 1):
                cell = ws_exp.cell(row=row_idx, column=c, value=v)
                cell.border = THIN_BORDER
                cell.alignment = LEFT
                cell.font = NORMAL_FONT
                if row_idx % 2 == 0:
                    cell.fill = ACCENT_FILL

        _auto_width(ws_exp)

    # ── Sheet 3: Income ───────────────────────────────────────────────────────
    if income:
        ws_inc = wb.create_sheet("Income")
        ws_inc.merge_cells("A1:E1")
        ws_inc["A1"].value = "📈 Income Transactions"
        ws_inc["A1"].font = TITLE_FONT
        ws_inc["A1"].alignment = CENTER

        inc_headers = ["Date", "Source", "Description", "Amount (EGP)", "Currency"]
        for col, h in enumerate(inc_headers, 1):
            ws_inc.cell(row=2, column=col, value=h)
        _style_header_row(ws_inc, 2, len(inc_headers))

        for row_idx, row in enumerate(income, start=3):
            created_at = row.get("created_at")
            if hasattr(created_at, "strftime"):
                date_str = created_at.strftime("%Y-%m-%d %H:%M")
            else:
                date_str = str(created_at)[:16] if created_at else ""

            values = [
                date_str,
                row.get("item", ""),
                row.get("description", ""),
                float(row.get("amount") or 0),
                row.get("currency", "EGP"),
            ]
            for c, v in enumerate(values, 1):
                cell = ws_inc.cell(row=row_idx, column=c, value=v)
                cell.border = THIN_BORDER
                cell.alignment = LEFT
                cell.font = NORMAL_FONT
                if row_idx % 2 == 0:
                    cell.fill = ACCENT_FILL

        _auto_width(ws_inc)

    # ── Sheet 4: Chart ────────────────────────────────────────────────────────
    if expenses:
        ws_chart = wb.create_sheet("Chart")
        ws_chart["A1"].value = "Chart Data"
        ws_chart["A1"].font = TITLE_FONT

        ws_chart.cell(row=2, column=1, value="Category")
        ws_chart.cell(row=2, column=2, value="Total (EGP)")
        _style_header_row(ws_chart, 2, 2)

        for row_idx, (cat, data) in enumerate(
            sorted(category_totals.items(), key=lambda x: -x[1]["total"]), start=3
        ):
            ws_chart.cell(row=row_idx, column=1, value=cat)
            ws_chart.cell(row=row_idx, column=2, value=round(data["total"], 2))

        last_data_row = ws_chart.max_row
        
        # Create Pie Chart instead of Bar Chart
        chart = PieChart()
        chart.title = "Expenses by Category"
        
        data_ref = Reference(ws_chart, min_col=2, min_row=2, max_row=last_data_row)
        cats_ref = Reference(ws_chart, min_col=1, min_row=3, max_row=last_data_row)
        chart.add_data(data_ref, titles_from_data=True)
        chart.set_categories(cats_ref)
        
        # Position the chart
        ws_chart.add_chart(chart, "D2")

        _auto_width(ws_chart)

    # ── Serialize to buffer ───────────────────────────────────────────────────
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


async def export_excel_report(sql_result: dict, bot: Bot, chat_id: int, current_date: str | None = None) -> bool:
    """
    Generates the Excel report and sends it via Telegram.
    Returns True on success, False on error.
    """
    try:
        buffer = generate_excel_report(sql_result, current_date)

        today_str = (current_date or datetime.now(timezone.utc).isoformat())[:10]
        filename = f"finance_report_{today_str}.xlsx"

        total_transactions = len(sql_result.get("expenses", [])) + len(sql_result.get("income", []))

        await bot.send_document(
            chat_id=chat_id,
            document=buffer,
            filename=filename,
            caption=(
                "📊 *تقريرك المالي الشامل جاهز!*\n"
                f"يحتوي على {total_transactions} معاملة (مصاريف ودخل) 💼\n\n"
                "افتح الملف لتشوف الملخص والـ Pie Chart 📈"
            ),
            parse_mode="Markdown",
        )
        return True

    except Exception as e:
        logger.error(f"Excel export error: {e}", exc_info=True)
        return False

