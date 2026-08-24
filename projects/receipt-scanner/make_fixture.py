"""Render synthetic receipts, to test the plumbing before real photographs.

What this is for: proving the schema, the API call, the parse, and the
interpretation all fit together. Run it once, point extract.py at the output,
and any wiring fault shows up without burning a real receipt.

What this is NOT for: measuring extraction accuracy. These are crisp rendered
text on white — nothing like a curled thermal slip photographed under a kitchen
light, and the "handwritten" tip is a font, not handwriting. The Daily Brief
learned this the expensive way: six real newsletters found four bugs in ten
seconds that no amount of fixture-writing had surfaced. Accuracy numbers come
from photographs of real receipts, and only from those.

    python make_fixture.py
    python extract.py samples/fixture_restaurant.png
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SAMPLES = Path(__file__).parent / "samples"

WIDTH = 640
BACKGROUND = (250, 249, 245)
INK = (35, 33, 30)
PEN = (20, 30, 120)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for name in (("consolab.ttf", "consola.ttf") if bold else ("consola.ttf",)):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.truetype("cour.ttf", size)
    except OSError:
        return ImageFont.load_default(size)


def _slip(name: str, lines: list[tuple[str, str, bool]], title: str, footer: list[str]) -> Path:
    """Render one receipt. Each line is (left, right, handwritten)."""
    body = _font(19)
    head = _font(26, bold=True)
    pen = _font(27, bold=True)

    height = 200 + len(lines) * 34 + len(footer) * 26
    img = Image.new("RGB", (WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(img)

    y = 34
    draw.text((WIDTH // 2, y), title, font=head, fill=INK, anchor="ma")
    y += 52
    draw.line([(40, y), (WIDTH - 40, y)], fill=INK, width=1)
    y += 22

    for left, right, handwritten in lines:
        if left == "---":
            draw.line([(40, y + 10), (WIDTH - 40, y + 10)], fill=INK, width=1)
            y += 30
            continue
        font = pen if handwritten else body
        colour = PEN if handwritten else INK
        draw.text((44, y), left, font=body, fill=INK)
        if right:
            draw.text((WIDTH - 44, y - (6 if handwritten else 0)), right,
                      font=font, fill=colour, anchor="ra")
        y += 34

    y += 12
    for line in footer:
        draw.text((WIDTH // 2, y), line, font=body, fill=INK, anchor="ma")
        y += 26

    SAMPLES.mkdir(exist_ok=True)
    path = SAMPLES / name
    img.save(path)
    return path


def restaurant() -> Path:
    """A tip written as ``10-`` and a handwritten total — the hard case."""
    return _slip(
        "fixture_restaurant.png",
        title="THE ANGUS BARN",
        lines=[
            ("SERVER: DANA      TBL 12", "", False),
            ("08/01/26  7:42 PM", "", False),
            ("---", "", False),
            ("RIBEYE 12OZ", "38.00", False),
            ("ICED TEA", "4.00", False),
            ("---", "", False),
            ("SUBTOTAL", "42.00", False),
            ("TAX", "3.36", False),
            ("AMOUNT", "45.36", False),
            ("---", "", False),
            ("TIP", "10-", True),
            ("TOTAL", "55.36", True),
        ],
        footer=["VISA ************4242", "APPROVED  AUTH 004417",
                "THANK YOU"],
    )


def hardware() -> Path:
    """A warranty item, no tip line — should extract clean."""
    return _slip(
        "fixture_hardware.png",
        title="LOWE'S #1247",
        lines=[
            ("RALEIGH NC", "", False),
            ("03/17/26  10:14 AM", "", False),
            ("---", "", False),
            ("DEWALT 20V DRILL", "24.98", False),
            ("DRYWALL SCREWS 1LB", "4.33", False),
            ("---", "", False),
            ("SUBTOTAL", "29.31", False),
            ("TAX", "2.21", False),
            ("TOTAL", "31.52", False),
        ],
        footer=["VISA ************8557", "3 YEAR LIMITED WARRANTY",
                "RETURN WITHIN 90 DAYS"],
    )


def cash_tip() -> Path:
    """CASH written in the tip box — zero charged to the card."""
    return _slip(
        "fixture_cash_tip.png",
        title="CITY DINER",
        lines=[
            ("08/02/26  8:15 AM", "", False),
            ("---", "", False),
            ("BREAKFAST PLATE", "14.00", False),
            ("COFFEE", "4.00", False),
            ("---", "", False),
            ("SUBTOTAL", "18.00", False),
            ("TAX", "1.44", False),
            ("---", "", False),
            ("TIP", "CASH", True),
            ("TOTAL", "19.44", True),
        ],
        footer=["MASTERCARD ****1111"],
    )


if __name__ == "__main__":
    for build in (restaurant, hardware, cash_tip):
        path = build()
        print(f"wrote {path}")
    print("\nThese test the wiring, not the reading. Accuracy numbers come from")
    print("photographs of real receipts.")
