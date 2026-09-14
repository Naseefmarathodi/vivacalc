"""Excel and PDF generation for the booking ledger.

Two rules govern this module:

1. Money is never *computed* in float. Row values are the ``Decimal`` objects
   the ORM returns, and every total comes from a database ``SUM`` rather than
   from accumulating the rows in Python, so an exported total is always the
   same number the screen showed.

   One limit is worth stating plainly: the .xlsx format itself stores numbers
   as IEEE-754 doubles (ECMA-376), and openpyxl serialises them at full double
   precision — a cell holding 0.07 is written as ``0.07000000000000001``. No
   library can put a true decimal in a numeric Excel cell. What this module
   guarantees instead is that nothing is *accumulated* in float (the original
   bug) and that every cell carries a 2-decimal currency format, so Excel
   displays, prints and re-sums the intended figures. The PDF has no such
   constraint: its values are formatted from Decimal directly.
2. The Viva logo is embedded byte-for-byte from ``static/logo.png``. It is
   never re-encoded, recoloured, cropped or regenerated — only scaled to fit
   its box, preserving the original aspect ratio.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("vivacalc.exports")

COLUMNS = [
    ("S.No", 6),
    ("Passenger", 26),
    ("Service", 28),
    ("Sector", 22),
    ("Portal", 16),
    ("Buy", 13),
    ("Sell", 13),
    ("Margin", 13),
    ("Entered By", 16),
    ("Date", 12),
]

BRAND_RED = "EC1C24"      # sampled from the Viva logo
BRAND_GREY = "A6A8AB"     # sampled from the Viva logo
INK = "1B2430"


class ExportTooLarge(Exception):
    """Raised when a requested export exceeds EXPORT_MAX_ROWS."""

    def __init__(self, count: int, limit: int):
        self.count, self.limit = count, limit
        super().__init__(
            f"This export covers {count:,} bookings, above the {limit:,}-row limit."
        )


def _logo_dimensions(max_width: float, max_height: float) -> tuple[float, float]:
    """Scale the logo into a box without distorting it."""
    from PIL import Image

    with Image.open(settings.BRAND_LOGO_PATH) as im:
        width, height = im.size
    ratio = min(max_width / width, max_height / height)
    return width * ratio, height * ratio


def _rows(queryset):
    """Yield (index, booking) with related objects already loaded."""
    qs = queryset.select_related("portal", "entered_by")
    for index, booking in enumerate(qs.iterator(chunk_size=500), start=1):
        yield index, booking


def _guard_size(queryset) -> int:
    count = queryset.count()
    limit = settings.EXPORT_MAX_ROWS
    if count > limit:
        raise ExportTooLarge(count, limit)
    return count


def _totals(queryset) -> dict[str, Decimal]:
    """Aggregate in the database, in Decimal. Never sum in Python floats."""
    from django.db.models import Sum

    result = queryset.aggregate(
        total_buy=Sum("buy_price"),
        total_sell=Sum("sell_price"),
        total_margin=Sum("margin"),
    )
    return {key: (value or Decimal("0.00")) for key, value in result.items()}


def _meta_lines(filter_descriptions: list[tuple[str, str]]) -> list[tuple[str, str]]:
    generated = timezone.localtime().strftime("%d %b %Y, %H:%M %Z")
    lines = [("Generated", generated)]
    lines.extend(filter_descriptions or [("Filters", "None — all bookings")])
    return lines


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
def build_workbook(queryset, filter_descriptions) -> BytesIO:
    """Return an .xlsx of *queryset* as an in-memory stream."""
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    _guard_size(queryset)

    wb = Workbook()
    ws = wb.active
    ws.title = "Bookings"

    thin = Side(style="thin", color="D5DAE1")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    money_format = '#,##0.00'

    # --- Logo, embedded from the original asset, aspect ratio preserved ----
    try:
        logo = XLImage(str(settings.BRAND_LOGO_PATH))
        logo.width, logo.height = _logo_dimensions(84, 84)
        ws.add_image(logo, "A1")
    except Exception:
        # An export must not fail because of a decorative image.
        logger.exception("could not embed logo in workbook")

    ws.row_dimensions[1].height = 30
    ws.row_dimensions[2].height = 22
    ws.row_dimensions[3].height = 18

    title = ws.cell(row=1, column=2, value=f"{settings.BRAND_NAME} — Booking Margin Report")
    title.font = Font(size=15, bold=True, color=INK)
    subtitle = ws.cell(row=2, column=2, value=settings.APP_NAME)
    subtitle.font = Font(size=10, bold=True, color=BRAND_RED)

    row = 4
    for label, value in _meta_lines(filter_descriptions):
        ws.cell(row=row, column=2, value=f"{label}:").font = Font(size=9, bold=True, color="5B6675")
        ws.cell(row=row, column=3, value=value).font = Font(size=9, color="5B6675")
        row += 1

    header_row = row + 1
    header_fill = PatternFill("solid", fgColor=BRAND_RED)
    for col, (label, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=header_row, column=col, value=label)
        cell.font = Font(bold=True, color="FFFFFF", size=10)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[header_row].height = 20

    data_row = header_row
    for index, booking in _rows(queryset):
        data_row += 1
        values = [
            index,
            booking.passenger_name,
            booking.service or "",
            booking.sector or "",
            booking.portal.name if booking.portal else "",
            booking.buy_price,      # Decimal, written natively
            booking.sell_price,     # Decimal
            booking.margin,         # Decimal
            booking.entered_by.username if booking.entered_by else "",
            timezone.localtime(booking.created_at).strftime("%Y-%m-%d"),
        ]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=data_row, column=col, value=value)
            cell.border = border
            cell.alignment = Alignment(
                horizontal="right" if col in (6, 7, 8) else "left", vertical="center"
            )
            if col in (6, 7, 8):
                cell.number_format = money_format

    totals = _totals(queryset)
    total_row = data_row + 1
    total_fill = PatternFill("solid", fgColor="F1F3F6")
    ws.cell(row=total_row, column=1, value="")
    label_cell = ws.cell(row=total_row, column=2, value="TOTAL")
    label_cell.font = Font(bold=True, size=11, color=INK)
    for col, key in ((6, "total_buy"), (7, "total_sell"), (8, "total_margin")):
        cell = ws.cell(row=total_row, column=col, value=totals[key])
        cell.font = Font(bold=True, size=11, color=INK)
        cell.number_format = money_format
        cell.alignment = Alignment(horizontal="right")
    for col in range(1, len(COLUMNS) + 1):
        ws.cell(row=total_row, column=col).fill = total_fill
        ws.cell(row=total_row, column=col).border = border

    # Keep the header visible while scrolling a long report.
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.print_title_rows = f"{header_row}:{header_row}"

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def build_pdf(queryset, filter_descriptions) -> BytesIO:
    """Return a paginated landscape A4 PDF of *queryset*."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        Image,
        PageBreak,
        PageTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )

    _guard_size(queryset)

    page_size = landscape(A4)
    page_width, page_height = page_size
    margin = 12 * mm
    brand_red = colors.HexColor(f"#{BRAND_RED}")
    brand_grey = colors.HexColor(f"#{BRAND_GREY}")
    ink = colors.HexColor(f"#{INK}")

    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle(
        "cell", parent=styles["BodyText"], fontSize=7.5, leading=9.5,
        textColor=ink, spaceAfter=0,
    )
    money_style = ParagraphStyle("money", parent=cell_style, alignment=TA_RIGHT)
    title_style = ParagraphStyle(
        "title", parent=styles["Title"], fontSize=15, leading=18,
        alignment=0, textColor=ink, spaceAfter=2,
    )
    meta_style = ParagraphStyle(
        "meta", parent=styles["BodyText"], fontSize=8, leading=11,
        textColor=colors.HexColor("#5B6675"),
    )

    stream = BytesIO()
    generated = timezone.localtime().strftime("%d %b %Y, %H:%M %Z")

    def draw_chrome(canvas, doc):
        """Footer on every page: brand rule, generation stamp, page number."""
        canvas.saveState()
        canvas.setStrokeColor(brand_grey)
        canvas.setLineWidth(0.5)
        canvas.line(margin, margin - 2 * mm, page_width - margin, margin - 2 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#5B6675"))
        canvas.drawString(
            margin, margin - 6 * mm,
            f"{settings.BRAND_NAME} · {settings.APP_NAME} · generated {generated}",
        )
        canvas.drawRightString(
            page_width - margin, margin - 6 * mm, f"Page {canvas.getPageNumber()}"
        )
        canvas.restoreState()

    doc = BaseDocTemplate(
        stream,
        pagesize=page_size,
        leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin + 6 * mm,
        title=f"{settings.BRAND_NAME} — Booking Margin Report",
        author=settings.BRAND_NAME,
    )
    frame = Frame(
        margin, doc.bottomMargin,
        page_width - 2 * margin, page_height - margin - doc.bottomMargin,
        id="body", showBoundary=0,
    )
    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=draw_chrome)])

    story = []

    # --- Header: original logo, unmodified, scaled proportionally ----------
    header_cells = []
    try:
        logo_w, logo_h = _logo_dimensions(22 * mm, 22 * mm)
        header_cells.append(Image(str(settings.BRAND_LOGO_PATH), width=logo_w, height=logo_h))
    except Exception:
        logger.exception("could not embed logo in PDF")
        header_cells.append(Paragraph("", meta_style))

    meta_html = "<br/>".join(
        f"<b>{label}:</b> {value}" for label, value in _meta_lines(filter_descriptions)
    )
    header_cells.append(
        [
            Paragraph("Booking Margin Report", title_style),
            Paragraph(settings.BRAND_NAME, meta_style),
            Spacer(1, 3),
            Paragraph(meta_html, meta_style),
        ]
    )
    header = Table(
        [[header_cells[0], header_cells[1]]],
        colWidths=[26 * mm, page_width - 2 * margin - 26 * mm],
    )
    header.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 0), (-1, -1), 1.2, brand_red),
        ])
    )
    story.extend([header, Spacer(1, 8)])

    # --- Table -------------------------------------------------------------
    head = [Paragraph(f"<b>{label}</b>", cell_style) for label, _ in COLUMNS]
    head[5] = Paragraph("<b>Buy</b>", money_style)
    head[6] = Paragraph("<b>Sell</b>", money_style)
    head[7] = Paragraph("<b>Margin</b>", money_style)
    data = [head]

    def money(value: Decimal) -> str:
        return f"{value:,.2f}"

    negative_rows = []
    row_index = 0
    for index, booking in _rows(queryset):
        row_index += 1
        if booking.margin is not None and booking.margin < 0:
            negative_rows.append(row_index)
        data.append([
            Paragraph(str(index), cell_style),
            Paragraph(booking.passenger_name or "", cell_style),
            Paragraph(booking.service or "", cell_style),
            Paragraph(booking.sector or "", cell_style),
            Paragraph(booking.portal.name if booking.portal else "", cell_style),
            Paragraph(money(booking.buy_price), money_style),
            Paragraph(money(booking.sell_price), money_style),
            Paragraph(money(booking.margin), money_style),
            Paragraph(
                booking.entered_by.username if booking.entered_by else "", cell_style
            ),
            Paragraph(
                timezone.localtime(booking.created_at).strftime("%d-%m-%Y"), cell_style
            ),
        ])

    totals = _totals(queryset)
    data.append([
        Paragraph("", cell_style),
        Paragraph("<b>TOTAL</b>", cell_style),
        Paragraph("", cell_style), Paragraph("", cell_style), Paragraph("", cell_style),
        Paragraph(f"<b>{money(totals['total_buy'])}</b>", money_style),
        Paragraph(f"<b>{money(totals['total_sell'])}</b>", money_style),
        Paragraph(f"<b>{money(totals['total_margin'])}</b>", money_style),
        Paragraph("", cell_style), Paragraph("", cell_style),
    ])

    if row_index == 0:
        story.append(Paragraph("No bookings match these filters.", meta_style))
    else:
        available = page_width - 2 * margin
        weights = [w for _, w in COLUMNS]
        scale = available / sum(weights)
        col_widths = [w * scale for w in weights]

        table = Table(data, colWidths=col_widths, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), brand_red),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D5DAE1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2),
             [colors.white, colors.HexColor("#F7F8FA")]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EDEFF3")),
            ("LINEABOVE", (0, -1), (-1, -1), 1, ink),
        ]
        for r in negative_rows:
            style.append(("TEXTCOLOR", (7, r), (7, r), colors.HexColor("#9B1C17")))
        table.setStyle(TableStyle(style))
        story.append(table)

    doc.build(story)
    stream.seek(0)
    return stream
