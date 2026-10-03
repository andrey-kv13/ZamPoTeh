from pathlib import Path

from fpdf import FPDF

from zampotex.config import PDF_DIR


def _font_path() -> Path | None:
    candidates = [
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def write_pdf(filename: str, text: str) -> Path | None:
    font = _font_path()
    if font is None:
        return None
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    target = PDF_DIR / filename
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.add_font("Body", "", str(font))
    pdf.set_font("Body", size=12)
    pdf.multi_cell(0, 7, text)
    pdf.output(str(target))
    return target
