import io
import logging
from datetime import datetime, timezone
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.chart import BarChart, Reference
from openpyxl.utils import get_column_letter
from telegram import Bot

logger = logging.getLogger(__name__)

# Color palette
HEADER_FILL  = PatternFill("solid", fgColor="2E86AB")   # Blue
ACCENT_FILL  = PatternFill("solid", fgColor="F6F6F6")   # Light grey alternating row
TOTAL_FILL   = PatternFill("solid", fgColor="A8DADC")   # Teal for totals
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


def generate_excel_report(sql_result: list[dict], current_date: str | None = None) -> io.BytesIO:
    """
    Generates a professional 3-sheet Excel workbook from sql_result rows.
    Returns an in-memory BytesIO buffer ready to send.

    sql_result rows must have keys: item, amount, currency, created_at, category
    """
    wb = openpyxl.Workbook()

    # ── Sheet 1: Summary by Category ─────────────────────────────────────────
    ws_summary = wb.active
    ws_summary.title = "Summary"

    ws_summary.merge_cells("A1:D1")
    title_cell = ws_summary["A1"]
    title_cell.value = "💰 Finance Report — Spending by Category"
    title_cell.font = TITLE_FONT
    title_cell.alignment = CENTER

    headers = ["Category", "Total (EGP)", "Transactions", "Average (EGP)"]
    for col, h in enumerate(headers, 1):
        ws_summary.cell(row=2, column=col, value=h)
    _style_header_row(ws_summary, 2, len(headers))

    # Aggregate by category
    category_totals: dict[str, dict] = {}
    for row in sql_result:
        cat = row.get("category", "Other")
        if cat not in category_totals:
            category_totals[cat] = {"total": 0.0, "count": 0}
        category_totals[cat]["total"] += float(row.get("amount") or 0)
        category_totals[cat]["count"] += 1

    for r, (cat, data) in enumerate(
        sorted(category_totals.items(), key=lambda x: -x[1]["total"]), start=3
    ):
        avg = round(data["total"] / data["count"], 2) if data["count"] else 0
        values = [cat, round(data["total"], 2), data["count"], avg]
        for c, v in enumerate(values, 1):
            cell = ws_summary.cell(row=r, column=c, value=v)
            cell.border = THIN_BORDER
            cell.alignment = LEFT
            cell.font = NORMAL_FONT
            if r % 2 == 0:
                cell.fill = ACCENT_FILL

    # Grand total row
    grand_total = sum(d["total"] for d in category_totals.values())
    total_row = ws_summary.max_row + 1
    ws_summary.cell(row=total_row, column=1, value="TOTAL").font = Font(bold=True)
    ws_summary.cell(row=total_row, column=2, value=round(grand_total, 2)).font = Font(bold=True)
    for c in range(1, 5):
        ws_summary.cell(row=total_row, column=c).fill = TOTAL_FILL
        ws_summary.cell(row=total_row, column=c).border = THIN_BORDER

    _auto_width(ws_summary)

    # ── Sheet 2: Transactions ─────────────────────────────────────────────────
    ws_trans = wb.create_sheet("Transactions")

    ws_trans.merge_cells("A1:E1")
    ws_trans["A1"].value = "📋 All Transactions"
    ws_trans["A1"].font = TITLE_FONT
    ws_trans["A1"].alignment = CENTER

    trans_headers = ["Date", "Item", "Category", "Amount (EGP)", "Currency"]
    for col, h in enumerate(trans_headers, 1):
        ws_trans.cell(row=2, column=col, value=h)
    _style_header_row(ws_trans, 2, len(trans_headers))

    for r, row in enumerate(sql_result, start=3):
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
            cell = ws_trans.cell(row=r, column=c, value=v)
            cell.border = THIN_BORDER
            cell.alignment = LEFT
            cell.font = NORMAL_FONT
            if r % 2 == 0:
                cell.fill = ACCENT_FILL

    _auto_width(ws_trans)

    # ── Sheet 3: Chart ────────────────────────────────────────────────────────
    ws_chart = wb.create_sheet("Chart")
    ws_chart["A1"].value = "Chart Data"
    ws_chart["A1"].font = TITLE_FONT

    ws_chart.cell(row=2, column=1, value="Category")
    ws_chart.cell(row=2, column=2, value="Total (EGP)")
    _style_header_row(ws_chart, 2, 2)

    for r, (cat, data) in enumerate(
        sorted(category_totals.items(), key=lambda x: -x[1]["total"]), start=3
    ):
        ws_chart.cell(row=r, column=1, value=cat)
        ws_chart.cell(row=r, column=2, value=round(data["total"], 2))

    last_data_row = ws_chart.max_row
    chart = BarChart()
    chart.type = "col"
    chart.title = "Spending by Category"
    chart.y_axis.title = "Total (EGP)"
    chart.x_axis.title = "Category"
    chart.style = 10
    chart.width = 20
    chart.height = 12

    data_ref = Reference(ws_chart, min_col=2, min_row=2, max_row=last_data_row)
    cats_ref = Reference(ws_chart, min_col=1, min_row=3, max_row=last_data_row)
    chart.add_data(data_ref, titles_from_data=True)
    chart.set_categories(cats_ref)
    ws_chart.add_chart(chart, "D2")

    _auto_width(ws_chart)

    # ── Serialize to buffer ───────────────────────────────────────────────────
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


async def export_excel_report(sql_result: list[dict], bot: Bot, chat_id: int, current_date: str | None = None) -> bool:
    """
    Generates the Excel report and sends it via Telegram.
    Returns True on success, False on error.
    """
    try:
        buffer = generate_excel_report(sql_result, current_date)

        today_str = (current_date or datetime.now(timezone.utc).isoformat())[:10]
        filename = f"finance_report_{today_str}.xlsx"

        await bot.send_document(
            chat_id=chat_id,
            document=buffer,
            filename=filename,
            caption=(
                "📊 *تقريرك المالي جاهز!*\n"
                f"يحتوي على {len(sql_result)} معاملة 💼\n\n"
                "افتح الملف لتشوف Summary + Chart 📈"
            ),
            parse_mode="Markdown",
        )
        return True

    except Exception as e:
        logger.error(f"Excel export error: {e}", exc_info=True)
        return False
