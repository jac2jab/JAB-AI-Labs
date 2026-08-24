"""One receipt as a PDF you can hand to someone.

A warranty claim wants the receipt; an accountant wants the receipt; neither
wants a link to a server on your home network. This produces a single file:
the photograph, the confirmed fields above it, and the transcript as real text
so the document is searchable.

**What this is not.** It is not word-positioned OCR. A true searchable scan
places each word invisibly over its own position in the image; that needs
per-word bounding boxes, which a vision model does not return. Here the text
sits in its own region of the document. Searching the PDF for a vendor, an
amount, or a line item works. Selecting a word by clicking it on the photograph
does not. Saying so is cheaper than implying otherwise.
"""

from __future__ import annotations

import io
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = LETTER
MARGIN = 0.75 * inch
INK = (0.1, 0.1, 0.1)
MUTED = (0.45, 0.45, 0.45)


def _money(value) -> str:
    return "—" if value is None else f"${value:,.2f}"


def _fields(receipt) -> list[tuple[str, str]]:
    rows = [
        ("Company", receipt.vendor or "—"),
        ("Date", receipt.purchased_on.isoformat() if receipt.purchased_on else "—"),
        ("Total charged", _money(receipt.total)),
        ("Tip", _money(receipt.tip)),
        ("Subtotal", _money(receipt.subtotal)),
        ("Tax", _money(receipt.tax)),
        ("Card", f"**** {receipt.card_last4}" if receipt.card_last4 else "—"),
        ("Payment", receipt.payment_method or "—"),
        ("Category", receipt.category or "—"),
        ("Warranty", "YES" if receipt.has_warranty else "NO"),
    ]
    if receipt.warranty_note:
        rows.append(("Warranty item", receipt.warranty_note))
    if receipt.retention_until:
        rows.append(("Keep until", receipt.retention_until.isoformat()))
    elif receipt.has_warranty:
        rows.append(("Keep until", "indefinitely"))
    return rows


def _wrap(text: str, width_chars: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if len(candidate) <= width_chars:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines


def build(receipt, image_path: Path | str) -> bytes:
    """Render the receipt to PDF bytes."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=LETTER)
    pdf.setTitle(f"{receipt.vendor or 'Receipt'} "
                 f"{receipt.purchased_on.isoformat() if receipt.purchased_on else ''}".strip())
    pdf.setAuthor("PixelScan Pro")
    pdf.setSubject("Receipt archive record")

    y = PAGE_H - MARGIN

    pdf.setFillColorRGB(*INK)
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawString(MARGIN, y, (receipt.vendor or "Receipt")[:40])
    y -= 26

    pdf.setFont("Helvetica", 10)
    pdf.setFillColorRGB(*MUTED)
    stamp = receipt.purchased_on.isoformat() if receipt.purchased_on else "no date"
    pdf.drawString(MARGIN, y, f"{stamp}   ·   {_money(receipt.total)}")
    y -= 24

    # Two columns of label/value, as selectable text.
    pdf.setFont("Helvetica", 10)
    column_width = (PAGE_W - 2 * MARGIN) / 2
    rows = _fields(receipt)
    start_y = y
    for index, (label, value) in enumerate(rows):
        column = index % 2
        if column == 0 and index:
            y -= 17
        x = MARGIN + column * column_width
        pdf.setFillColorRGB(*MUTED)
        pdf.drawString(x, y, f"{label}:")
        pdf.setFillColorRGB(*INK)
        pdf.drawString(x + 82, y, str(value)[:44])
    y -= 30

    pdf.setStrokeColorRGB(0.85, 0.85, 0.85)
    pdf.line(MARGIN, y, PAGE_W - MARGIN, y)
    y -= 16

    # The photograph, scaled into whatever room is left.
    image_path = Path(image_path)
    if image_path.exists():
        try:
            reader = ImageReader(str(image_path))
            src_w, src_h = reader.getSize()
            max_w = PAGE_W - 2 * MARGIN
            max_h = y - MARGIN
            scale = min(max_w / src_w, max_h / src_h)
            draw_w, draw_h = src_w * scale, src_h * scale
            pdf.drawImage(
                reader, MARGIN + (max_w - draw_w) / 2, y - draw_h,
                width=draw_w, height=draw_h, preserveAspectRatio=True, mask="auto",
            )
        except Exception as exc:  # a corrupt image must not lose the fields
            pdf.setFillColorRGB(*MUTED)
            pdf.setFont("Helvetica-Oblique", 9)
            pdf.drawString(MARGIN, y - 14, f"[image could not be embedded: {exc}]")

    # The transcript, on its own page, as searchable text.
    if receipt.transcript:
        pdf.showPage()
        y = PAGE_H - MARGIN
        pdf.setFillColorRGB(*INK)
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(MARGIN, y, "Transcript")
        y -= 20
        pdf.setFont("Courier", 9)
        pdf.setFillColorRGB(0.2, 0.2, 0.2)
        for line in _wrap(receipt.transcript, 92):
            if y < MARGIN:
                pdf.showPage()
                pdf.setFont("Courier", 9)
                pdf.setFillColorRGB(0.2, 0.2, 0.2)
                y = PAGE_H - MARGIN
            pdf.drawString(MARGIN, y, line[:96])
            y -= 12

    pdf.save()
    return buffer.getvalue()


if __name__ == "__main__":
    from dataclasses import dataclass
    from datetime import date
    from decimal import Decimal

    @dataclass
    class Fake:
        vendor = "The Angus Barn"
        purchased_on = date(2026, 8, 1)
        total = Decimal("55.36")
        tip = Decimal("10.00")
        subtotal = Decimal("42.00")
        tax = Decimal("3.36")
        card_last4 = "4242"
        payment_method = "VISA"
        category = "Restaurant"
        has_warranty = False
        warranty_note = None
        retention_until = date(2028, 8, 1)
        transcript = ("THE ANGUS BARN\nSERVER: DANA  TBL 12\n08/01/26 7:42 PM\n"
                      "RIBEYE 12OZ  38.00\nICED TEA  4.00\nSUBTOTAL 42.00\n"
                      "TAX 3.36\nAMOUNT 45.36\nTIP 10-\nTOTAL 55.36\n"
                      "VISA ************4242\nTHANK YOU")

    out = Path(__file__).parent / "data" / "sample_receipt.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    sample = Path(__file__).parent / "samples" / "fixture_restaurant.png"
    out.write_bytes(build(Fake(), sample))
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
