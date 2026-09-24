"""Génère un jeu de factures fictives avec leurs valeurs attendues.

Usage : uv run python -m evals.generate
"""

import json
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

TODAY = date(2026, 9, 24)
COMPANY = "Atelier Lumière SAS"
DATASET_DIR = Path(__file__).parent / "dataset"
CENT = Decimal("0.01")
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]

ADDRESSES = {
    COMPANY: "12 rue des Arts, 69002 Lyon",
    "Bureau Plus SARL": "8 avenue Jean Jaurès, 69007 Lyon",
    "Imprimerie Dupont": "45 rue Garibaldi, 69003 Lyon",
    "TechNet Services": "3 place Bellecour, 69002 Lyon",
    "Transports Martin": "Zone Industrielle Nord, 69120 Vaulx-en-Velin",
    "Hôtel Bellevue": "2 quai Saint-Antoine, 69002 Lyon",
    "Café des Arts": "7 rue Mercière, 69002 Lyon",
}


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def doc(file, supplier, number, issue, lines, *, doc_type="facture", due_days=30,
        vat_error=None, issues=(), accept=True, direction="recue", customer=COMPANY):
    ht = sum((money(q * money(p)) for _, q, p in lines), Decimal("0"))
    vat = money(ht * Decimal("0.20"))
    ttc = ht + vat
    printed_vat = vat + vat_error if vat_error is not None else vat
    due = issue + timedelta(days=due_days) if doc_type == "facture" else None
    codes = list(issues)
    if due is not None and due < TODAY and "ECHEANCE_DEPASSEE" not in codes:
        codes.append("ECHEANCE_DEPASSEE")
    return {
        "file": file,
        "expected_status": "anomalie" if codes else "ok",
        "expected_issues": codes,
        "accept": accept,
        "invoice": {
            "doc_type": doc_type,
            "direction": direction,
            "supplier": supplier,
            "customer": customer,
            "number": number,
            "issue_date": issue.isoformat(),
            "due_date": due.isoformat() if due else None,
            "amount_excl_tax": str(ht),
            "vat_amount": str(printed_vat),
            "amount_incl_tax": str(ttc),
        },
        "lines": [[label, qty, str(money(price))] for label, qty, price in lines],
    }


def build_specs() -> list[dict]:
    d = date
    return [
        doc("01_bureau_plus.pdf", "Bureau Plus SARL", "F-2026-101", d(2026, 9, 2),
            [("Ramettes papier A4", 20, 4.5), ("Stylos bille (boîte)", 5, 12.9), ("Classeurs", 10, 3.2)]),
        doc("02_dupont.pdf", "Imprimerie Dupont", "4512", d(2026, 9, 3),
            [("Flyers A5 x1000", 2, 89.0), ("Cartes de visite x500", 1, 45.0)]),
        doc("03_technet.pdf", "TechNet Services", "TN-889", d(2026, 9, 4),
            [("Maintenance informatique septembre", 1, 350.0)]),
        doc("04_bureau_plus.pdf", "Bureau Plus SARL", "F-2026-118", d(2026, 9, 8),
            [("Cartouches d'encre", 4, 38.0), ("Post-it (lot)", 6, 5.5)]),
        doc("05_martin.pdf", "Transports Martin", "TM/26/033", d(2026, 8, 11),
            [("Livraison Lyon - Grenoble", 1, 280.0), ("Manutention", 2, 35.0)]),
        doc("06_bureau_plus.pdf", "Bureau Plus SARL", "F-2026-131", d(2026, 9, 12),
            [("Chaises de bureau", 1, 189.0), ("Lampe LED", 2, 29.9)]),
        doc("07_dupont_scan.png", "Imprimerie Dupont", "4580", d(2026, 9, 14),
            [("Affiches A2 x50", 1, 160.0)]),
        doc("08_technet_tva.pdf", "TechNet Services", "TN-902", d(2026, 9, 15),
            [("Licence antivirus (12 mois)", 10, 24.0)], vat_error=Decimal("12.00"),
            issues=["TOTAL_INCOHERENT"], accept=False),
        doc("09_bureau_plus_doublon.pdf", "Bureau Plus SARL", "F-2026-101", d(2026, 9, 2),
            [("Ramettes papier A4", 20, 4.5), ("Stylos bille (boîte)", 5, 12.9), ("Classeurs", 10, 3.2)],
            issues=["DOUBLON"], accept=False),
        doc("10_dupont_devis.pdf", "Imprimerie Dupont", "D-2026-044", d(2026, 9, 16),
            [("Brochures 16 pages x500", 1, 740.0)], doc_type="devis"),
        doc("11_martin.pdf", "Transports Martin", "TM/26/041", d(2026, 9, 1),
            [("Livraison Lyon - Annecy", 1, 240.0)]),
        doc("12_bureau_plus_inhabituel.pdf", "Bureau Plus SARL", "F-2026-150", d(2026, 9, 18),
            [("Bureaux assis-debout", 8, 495.0)], issues=["MONTANT_INHABITUEL"]),
        doc("13_emise_bellevue.pdf", COMPANY, "AL-2026-057", d(2026, 8, 5),
            [("Luminaires sur mesure", 3, 420.0), ("Pose", 1, 180.0)],
            direction="emise", customer="Hôtel Bellevue"),
        {
            "file": "14_courrier.pdf",
            "expected_status": "a_revoir",
            "expected_issues": [],
            "accept": False,
            "invoice": None,
            "letter": True,
        },
        doc("15_dupont_tva.pdf", "Imprimerie Dupont", "4633", d(2026, 9, 20),
            [("Kakémono 80x200", 2, 115.0)], vat_error=Decimal("-18.40"),
            issues=["TOTAL_INCOHERENT"], accept=False),
        doc("16_martin_doublon.pdf", "Transports Martin", "TM/26/033", d(2026, 8, 11),
            [("Livraison Lyon - Grenoble", 1, 280.0), ("Manutention", 2, 35.0)],
            issues=["DOUBLON"], accept=False),
        doc("17_technet_devis.pdf", "TechNet Services", "DV-310", d(2026, 9, 21),
            [("Remplacement serveur", 1, 2400.0), ("Installation", 1, 450.0)], doc_type="devis"),
        doc("18_bureau_plus.pdf", "Bureau Plus SARL", "F-2026-162", d(2026, 9, 22),
            [("Enveloppes (x500)", 2, 19.0)]),
        doc("19_emise_cafe.pdf", COMPANY, "AL-2026-071", d(2026, 9, 22),
            [("Suspensions design", 4, 145.0)], direction="emise", customer="Café des Arts"),
        doc("20_dupont.pdf", "Imprimerie Dupont", "4701", d(2026, 9, 23),
            [("Étiquettes adhésives x2000", 1, 132.0)]),
    ]


def _fmt_date(value: date, layout: int) -> str:
    return value.strftime("%d/%m/%Y") if layout == 0 else f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def _fmt_money(value: Decimal) -> str:
    return f"{value:,.2f} €".replace(",", " ").replace(".", ",")


def _text_lines(spec: dict, layout: int) -> list[str]:
    inv = spec["invoice"]
    title = "FACTURE" if inv["doc_type"] == "facture" else "DEVIS"
    out = [inv["supplier"], ADDRESSES[inv["supplier"]], "", f"{title} N° {inv['number']}",
           f"Date : {_fmt_date(date.fromisoformat(inv['issue_date']), layout)}"]
    if inv["due_date"]:
        out.append(f"Échéance : {_fmt_date(date.fromisoformat(inv['due_date']), layout)}")
    else:
        out.append("Devis valable 30 jours")
    out += ["", f"Client : {inv['customer']}", ADDRESSES[inv["customer"]], "", "Désignation | Qté | PU HT | Total HT"]
    for label, qty, price in spec["lines"]:
        total = money(qty * Decimal(price))
        out.append(f"{label} | {qty} | {_fmt_money(Decimal(price))} | {_fmt_money(total)}")
    out += ["", f"Total HT : {_fmt_money(Decimal(inv['amount_excl_tax']))}",
            f"TVA 20 % : {_fmt_money(Decimal(inv['vat_amount']))}",
            f"Total TTC : {_fmt_money(Decimal(inv['amount_incl_tax']))}"]
    return out


def render_pdf(spec: dict, path: Path, layout: int) -> None:
    pdf = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 60
    x = 50 if layout == 0 else 70
    for i, line in enumerate(_text_lines(spec, layout)):
        pdf.setFont("Helvetica-Bold" if i in (0, 3) or line.startswith("Total TTC") else "Helvetica", 11)
        if line.startswith(("Total", "TVA")) and layout == 1:
            pdf.drawRightString(width - 60, y, line)
        else:
            pdf.drawString(x, y, line)
        y -= 18
    pdf.save()


def render_letter(path: Path) -> None:
    pdf = canvas.Canvas(str(path), pagesize=A4)
    lines = ["Transports Martin", "", "Objet : changement d'adresse de notre siège", "",
             "Madame, Monsieur,", "Nous vous informons que notre siège social déménage au 1er octobre 2026.",
             "Merci de mettre à jour vos coordonnées.", "", "Cordialement, la direction"]
    y = A4[1] - 60
    for line in lines:
        pdf.drawString(50, y, line)
        y -= 18
    pdf.save()


def _load_font(size: int):
    """Load a font that supports UTF-8 accented characters."""
    try:
        from PIL import ImageFont as IFont
        # Try common system font paths on macOS and Linux
        font_paths = [
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        for font_path in font_paths:
            if Path(font_path).exists():
                try:
                    return IFont.truetype(font_path, size)
                except Exception:
                    pass
    except Exception:
        pass
    # Fallback to default font
    return ImageFont.load_default(size=size)


def render_scan(spec: dict, path: Path) -> None:
    rng = random.Random(42)
    image = Image.new("L", (1240, 1754), color=245)
    draw = ImageDraw.Draw(image)
    font = _load_font(26)
    y = 80
    for line in _text_lines(spec, 0):
        draw.text((90, y), line, fill=30, font=font)
        y += 40
    for _ in range(4000):
        draw.point((rng.randrange(1240), rng.randrange(1754)), fill=rng.randrange(120, 200))
    image = image.rotate(1.5, fillcolor=245).filter(ImageFilter.GaussianBlur(0.8))
    image.save(path)


def generate(out_dir: Path = DATASET_DIR) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    specs = build_specs()
    for index, spec in enumerate(specs):
        path = out_dir / spec["file"]
        if spec.get("letter"):
            render_letter(path)
        elif path.suffix == ".png":
            render_scan(spec, path)
        else:
            render_pdf(spec, path, layout=index % 2)
    documents = [{k: v for k, v in s.items() if k in ("file", "expected_status", "expected_issues", "accept", "invoice")}
                 for s in specs]
    (out_dir / "expected.json").write_text(
        json.dumps({"today": TODAY.isoformat(), "documents": documents}, ensure_ascii=False, indent=2)
    )
    return specs


if __name__ == "__main__":
    generated = generate()
    print(f"{len(generated)} documents générés dans {DATASET_DIR}")
