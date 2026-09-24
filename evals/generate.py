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
DEFAULT_RATE = Decimal("0.20")
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
    "Épicerie Fine du Rhône": "18 rue de Brest, 69002 Lyon",
    "Électricité Lyon Pro": "27 avenue Berthelot, 69007 Lyon",
    "Nordic Lamps Ltd": "14 Harbour Road, Dublin 2, Ireland",
    "Restaurant Le Gourmet": "5 place des Terreaux, 69001 Lyon",
    "Galerie Nova": "31 rue Auguste Comte, 69002 Lyon",
}

LEGAL_FOOTER = [
    "SIRET 812 345 678 00021 — TVA intracommunautaire FR12 812345678 — RCS Lyon",
    "Pénalités de retard : 3 fois le taux d'intérêt légal. Indemnité forfaitaire pour frais de recouvrement : 40 €.",
    "Pas d'escompte pour paiement anticipé.",
]


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def _vat_by_rate(lines: list[tuple]) -> dict[Decimal, Decimal]:
    """Base HT par taux de TVA."""
    bases: dict[Decimal, Decimal] = {}
    for _, qty, price, rate in lines:
        bases[rate] = bases.get(rate, Decimal("0")) + money(qty * price)
    return bases


def doc(file, supplier, number, issue, lines, *, doc_type="facture", due_days=30,
        vat_error=None, ht_offset=None, issues=(), accept=True, direction="recue",
        customer=COMPANY, layout=None, lang="fr", scan=None):
    """Spécification d'une pièce et de sa vérité terrain.

    `lines` : (libellé, quantité, prix unitaire HT[, taux de TVA]) — taux 20 % par défaut.
    `vat_error` : écart ajouté à la TVA imprimée (TOTAL_INCOHERENT).
    `ht_offset` : écart ajouté au total HT imprimé, TVA et TTC restant cohérents avec lui
    (la somme des lignes ne correspond plus au HT : LIGNES_INCOHERENTES).
    """
    lines = [(label, qty, money(price), Decimal(str(rest[0])) if rest else DEFAULT_RATE)
             for label, qty, price, *rest in lines]
    bases = _vat_by_rate(lines)
    lines_total = sum(bases.values(), Decimal("0"))
    if ht_offset is not None:
        (rate,) = bases
        ht = lines_total + ht_offset
        vat = money(ht * rate)
    else:
        ht = lines_total
        vat = sum((money(base * rate) for rate, base in bases.items()), Decimal("0"))
    ttc = ht + vat
    printed_vat = vat + vat_error if vat_error is not None else vat
    due = issue + timedelta(days=due_days) if doc_type == "facture" and due_days is not None else None
    codes = list(issues)
    if due is not None and due < TODAY and "ECHEANCE_DEPASSEE" not in codes:
        codes.append("ECHEANCE_DEPASSEE")
    spec = {
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
            "lines": [
                {"description": label, "quantity": qty, "unit_price": str(price), "total": str(money(qty * price))}
                for label, qty, price, _ in lines
            ],
        },
        "lines": [[label, qty, str(price), str(rate)] for label, qty, price, rate in lines],
    }
    if layout is not None:
        spec["layout"] = layout
    if lang != "fr":
        spec["lang"] = lang
    if scan:
        spec["scan"] = scan
    return spec


def other(file, text):
    """Pièce qui n'est ni une facture ni un devis : l'agent doit la mettre « à revoir »."""
    return {"file": file, "expected_status": "a_revoir", "expected_issues": [], "accept": False,
            "invoice": None, "text": text}


def _multipage_lines() -> list[tuple]:
    products = [("Câble RJ45 Cat6", 4.9), ("Adaptateur USB-C", 12.0), ("Clavier sans fil", 29.0),
                ("Souris optique", 14.5), ("Hub USB 4 ports", 19.9), ("Barrette RAM 16 Go", 42.0),
                ("SSD 1 To", 79.0), ("Support d'écran", 34.0), ("Casque audio", 49.0),
                ("Webcam HD", 39.0), ("Multiprise parafoudre", 24.5), ("Tapis de souris", 6.5)]
    return [(f"{name} — lot {variant}", variant, price) for name, price in products for variant in (1, 2, 3)]


def build_specs() -> list[dict]:
    d = date
    return [
        # --- Jeu initial (documents 01 à 20) ---
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
        other("14_courrier.pdf", [
            "Transports Martin", "", "Objet : changement d'adresse de notre siège", "",
            "Madame, Monsieur,", "Nous vous informons que notre siège social déménage au 1er octobre 2026.",
            "Merci de mettre à jour vos coordonnées.", "", "Cordialement, la direction"]),
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
        # --- Cas réalistes supplémentaires (documents 21 à 40) ---
        doc("21_epicerie_multi_tva.pdf", "Épicerie Fine du Rhône", "EFR-2026-0412", d(2026, 9, 5),
            [("Plateaux repas", 25, 14.5, "0.10"), ("Jus de fruits (bouteille 1 L)", 12, 3.2, "0.055"),
             ("Vaisselle jetable (lot)", 3, 18.0, "0.20")], layout=2),
        doc("22_electricite_sans_echeance.pdf", "Électricité Lyon Pro", "EL-5487", d(2026, 9, 9),
            [("Installation de spots LED", 12, 45.0), ("Fourniture câblage", 1, 160.0)],
            due_days=None, layout=2),
        doc("23_technet_multipage.pdf", "TechNet Services", "TN-941", d(2026, 9, 10),
            _multipage_lines(), layout=0),
        doc("24_bureau_plus_doublon_format.pdf", "Bureau Plus SARL", "F2026-118", d(2026, 9, 8),
            [("Cartouches d'encre", 4, 38.0), ("Post-it (lot)", 6, 5.5)],
            issues=["DOUBLON"], accept=False, layout=1),
        doc("25_nordic_lamps_en.pdf", "Nordic Lamps Ltd", "INV-20931", d(2026, 9, 10),
            [("Pendant lamp NORD-40", 6, 89.0, "0"), ("Floor lamp FJORD", 2, 245.0, "0")],
            lang="en", layout=0),
        doc("26_martin_scan_degrade.png", "Transports Martin", "TM/26/052", d(2026, 9, 12),
            [("Livraison Lyon - Chambéry", 1, 260.0), ("Hayon élévateur", 1, 40.0)], scan="degrade"),
        doc("27_emise_gourmet.pdf", COMPANY, "AL-2026-078", d(2026, 9, 15),
            [("Appliques murales laiton", 6, 125.0), ("Pose", 1, 220.0)],
            direction="emise", customer="Restaurant Le Gourmet", layout=2),
        doc("28_emise_galerie_retard.pdf", COMPANY, "AL-2026-049", d(2026, 7, 20),
            [("Éclairage sur rail (installation)", 1, 1850.0)],
            direction="emise", customer="Galerie Nova", layout=1),
        doc("29_dupont.pdf", "Imprimerie Dupont", "4755", d(2026, 9, 16),
            [("Tampons encreurs", 3, 18.0)], layout=2),
        doc("30_dupont_inhabituel.pdf", "Imprimerie Dupont", "4790", d(2026, 9, 17),
            [("Signalétique complète showroom", 1, 2000.0)], issues=["MONTANT_INHABITUEL"], layout=0),
        doc("31_epicerie_lignes.pdf", "Épicerie Fine du Rhône", "EFR-2026-0431", d(2026, 9, 18),
            [("Plateaux repas", 20, 14.5, "0.10"), ("Desserts", 20, 4.2, "0.10")],
            ht_offset=Decimal("15.00"), issues=["LIGNES_INCOHERENTES"], accept=False, layout=1),
        other("32_bureau_plus_avoir.pdf", [
            "Bureau Plus SARL", ADDRESSES["Bureau Plus SARL"], "", "AVOIR N° AV-2026-007", "Date : 19/09/2026", "",
            f"Client : {COMPANY}", ADDRESSES[COMPANY], "",
            "En référence à notre facture F-2026-131 du 12/09/2026", "Retour : Lampe LED x 2", "",
            "Montant HT : -59,80 €", "TVA 20 % : -11,96 €", "Montant TTC à déduire : -71,76 €"]),
        other("33_martin_bon_livraison.pdf", [
            "Transports Martin", ADDRESSES["Transports Martin"], "", "BON DE LIVRAISON N° BL-8841",
            "Date de livraison : 17/09/2026", "", f"Destinataire : {COMPANY}", ADDRESSES[COMPANY], "",
            "Colis : 3 — Poids total : 42 kg", "Contenu : cartons de luminaires (réf. commande AL-CMD-311)", "",
            "Livré en bon état — signature du destinataire : ________"]),
        doc("34_electricite_devis.pdf", "Électricité Lyon Pro", "DEV-2026-12", d(2026, 9, 19),
            [("Mise aux normes du showroom", 1, 3200.0), ("Éclairage de secours", 6, 85.0)],
            doc_type="devis", layout=2),
        doc("35_technet_retard.pdf", "TechNet Services", "TN-950", d(2026, 8, 10),
            [("Maintenance informatique août", 1, 350.0)], layout=1),
        doc("36_emise_bellevue.pdf", COMPANY, "AL-2026-083", d(2026, 9, 19),
            [("Lampes de chevet", 20, 65.0)], direction="emise", customer="Hôtel Bellevue", layout=0),
        doc("37_nordic_lamps_en.pdf", "Nordic Lamps Ltd", "INV-20977", d(2026, 9, 21),
            [("Wall light LUMA", 10, 39.0, "0")], lang="en", layout=1),
        doc("38_dupont_scan.png", "Imprimerie Dupont", "4801", d(2026, 9, 21),
            [("Cartes de vœux x200", 1, 95.0)]),
        doc("39_bureau_plus.pdf", "Bureau Plus SARL", "F-2026-175", d(2026, 9, 22),
            [("Agrafeuses", 5, 12.5), ("Boîtes d'archives", 20, 2.9)], layout=2),
        doc("40_electricite_tva.pdf", "Électricité Lyon Pro", "EL-5520", d(2026, 9, 23),
            [("Remplacement tableau électrique", 1, 780.0), ("Main d'œuvre (heure)", 4, 55.0)],
            vat_error=Decimal("20.00"), issues=["TOTAL_INCOHERENT"], accept=False, layout=2),
    ]


# --- Mise en forme ---

def _fmt_date(value: date, layout: int, lang: str = "fr") -> str:
    if lang == "en":
        return f"{value:%B} {value.day}, {value.year}"
    return value.strftime("%d/%m/%Y") if layout != 1 else f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def _fmt_money(value: Decimal, lang: str = "fr") -> str:
    if lang == "en":
        return f"€{value:,.2f}"
    return f"{value:,.2f} €".replace(",", " ").replace(".", ",")


def _fmt_rate(rate: Decimal) -> str:
    return format((rate * 100).normalize(), "f").replace(".", ",")


def _parsed_lines(spec: dict) -> list[tuple]:
    return [(label, qty, Decimal(price), Decimal(rate)) for label, qty, price, rate in spec["lines"]]


def _vat_lines(spec: dict, lang: str) -> list[str]:
    inv = spec["invoice"]
    bases = _vat_by_rate(_parsed_lines(spec))
    vat_total = Decimal(inv["vat_amount"])
    if lang == "en":
        return [f"VAT 0% (reverse charge, art. 196 Directive 2006/112/EC): {_fmt_money(vat_total, lang)}"]
    if len(bases) == 1:
        (rate,) = bases
        return [f"TVA {_fmt_rate(rate)} % : {_fmt_money(vat_total)}"]
    lines = [f"TVA {_fmt_rate(rate)} % : {_fmt_money(money(base * rate))}" for rate, base in sorted(bases.items())]
    return lines + [f"Total TVA : {_fmt_money(vat_total)}"]


def _text_lines(spec: dict, layout: int) -> list[str]:
    inv = spec["invoice"]
    lang = spec.get("lang", "fr")
    en = lang == "en"
    if en:
        title = "INVOICE No."
    else:
        title = ("FACTURE" if inv["doc_type"] == "facture" else "DEVIS") + " N°"
    out = [inv["supplier"], ADDRESSES[inv["supplier"]], "", f"{title} {inv['number']}",
           f"{'Date:' if en else 'Date :'} {_fmt_date(date.fromisoformat(inv['issue_date']), layout, lang)}"]
    if inv["due_date"]:
        label = "Due date:" if en else "Échéance :"
        out.append(f"{label} {_fmt_date(date.fromisoformat(inv['due_date']), layout, lang)}")
    elif inv["doc_type"] == "devis":
        out.append("Devis valable 30 jours")
    out += ["", f"{'Bill to:' if en else 'Client :'} {inv['customer']}", ADDRESSES[inv["customer"]], "",
            "Description | Qty | Unit price | Amount" if en else "Désignation | Qté | PU HT | Total HT"]
    for label, qty, price, _ in _parsed_lines(spec):
        out.append(f"{label} | {qty} | {_fmt_money(price, lang)} | {_fmt_money(money(qty * price), lang)}")
    out += ["", f"{'Subtotal:' if en else 'Total HT :'} {_fmt_money(Decimal(inv['amount_excl_tax']), lang)}"]
    out += _vat_lines(spec, lang)
    out.append(f"{'Total:' if en else 'Total TTC :'} {_fmt_money(Decimal(inv['amount_incl_tax']), lang)}")
    return out


def render_pdf(spec: dict, path: Path, layout: int) -> None:
    """Mises en page 0 et 1 : texte simple, sur plusieurs pages si nécessaire."""
    pdf = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 60
    x = 50 if layout == 0 else 70
    for i, line in enumerate(_text_lines(spec, layout)):
        if y < 70:
            pdf.showPage()
            y = height - 60
        is_total = line.startswith(("Total", "TVA", "Subtotal", "VAT"))
        bold = i in (0, 3) or line.startswith(("Total TTC", "Total:"))
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", 11)
        if is_total and layout == 1:
            pdf.drawRightString(width - 60, y, line)
        else:
            pdf.drawString(x, y, line)
        y -= 18
    pdf.save()


def render_table_pdf(spec: dict, path: Path) -> None:
    """Mise en page 2 : logo, bloc client, tableau en colonnes et mentions légales en pied de page."""
    inv = spec["invoice"]
    pdf = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    initials = "".join(word[0] for word in inv["supplier"].split()[:2]).upper()
    pdf.setFillColorRGB(0.15, 0.3, 0.55)
    pdf.roundRect(50, height - 110, 60, 60, 8, fill=1, stroke=0)
    pdf.setFillColorRGB(1, 1, 1)
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawCentredString(80, height - 88, initials)
    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(125, height - 68, inv["supplier"])
    pdf.setFont("Helvetica", 9)
    pdf.drawString(125, height - 82, ADDRESSES[inv["supplier"]])

    title = "FACTURE" if inv["doc_type"] == "facture" else "DEVIS"
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawRightString(width - 50, height - 68, title)
    pdf.setFont("Helvetica", 10)
    meta = [f"N° {inv['number']}", f"Date d'émission : {_fmt_date(date.fromisoformat(inv['issue_date']), 0)}"]
    if inv["due_date"]:
        meta.append(f"Échéance : {_fmt_date(date.fromisoformat(inv['due_date']), 0)}")
    elif inv["doc_type"] == "devis":
        meta.append("Devis valable 30 jours")
    for i, text in enumerate(meta):
        pdf.drawRightString(width - 50, height - 86 - 14 * i, text)

    pdf.rect(width - 260, height - 205, 210, 55)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(width - 252, height - 162, "Facturé à :")
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(width - 252, height - 177, inv["customer"])
    pdf.setFont("Helvetica", 9)
    pdf.drawString(width - 252, height - 191, ADDRESSES[inv["customer"]])

    y = height - 250
    pdf.setFillColorRGB(0.9, 0.92, 0.95)
    pdf.rect(50, y - 5, width - 100, 18, fill=1, stroke=0)
    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(55, y, "Désignation")
    pdf.drawRightString(360, y, "Qté")
    pdf.drawRightString(440, y, "PU HT")
    pdf.drawRightString(width - 55, y, "Total HT")
    pdf.setFont("Helvetica", 9)
    for label, qty, price, rate in _parsed_lines(spec):
        y -= 18
        suffix = f" (TVA {_fmt_rate(rate)} %)" if len(_vat_by_rate(_parsed_lines(spec))) > 1 else ""
        pdf.drawString(55, y, label + suffix)
        pdf.drawRightString(360, y, str(qty))
        pdf.drawRightString(440, y, _fmt_money(price))
        pdf.drawRightString(width - 55, y, _fmt_money(money(qty * price)))
    pdf.line(50, y - 8, width - 50, y - 8)

    y -= 30
    totals = [f"Total HT : {_fmt_money(Decimal(inv['amount_excl_tax']))}", *_vat_lines(spec, "fr"),
              f"Total TTC : {_fmt_money(Decimal(inv['amount_incl_tax']))}"]
    for text in totals:
        pdf.setFont("Helvetica-Bold" if text.startswith("Total TTC") else "Helvetica", 10)
        pdf.drawRightString(width - 55, y, text)
        y -= 15

    pdf.setFont("Helvetica", 7)
    for i, text in enumerate(LEGAL_FOOTER):
        pdf.drawCentredString(width / 2, 50 - 10 * i, text)
    pdf.save()


def render_text(lines: list[str], path: Path) -> None:
    pdf = canvas.Canvas(str(path), pagesize=A4)
    y = A4[1] - 60
    for i, line in enumerate(lines):
        pdf.setFont("Helvetica-Bold" if i == 0 else "Helvetica", 11)
        pdf.drawString(50, y, line)
        y -= 18
    pdf.save()


def _load_font(size: int):
    """Police qui gère les accents et le symbole €, avec repli sur la police par défaut."""
    font_paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for font_path in font_paths:
        if Path(font_path).exists():
            try:
                return ImageFont.truetype(font_path, size)
            except OSError:
                pass
    return ImageFont.load_default(size=size)


def render_scan(spec: dict, path: Path) -> None:
    degraded = spec.get("scan") == "degrade"
    rng = random.Random(7 if degraded else 42)
    image = Image.new("L", (1240, 1754), color=238 if degraded else 245)
    draw = ImageDraw.Draw(image)
    font = _load_font(26)
    if degraded:  # taches sous le texte, comme une tache de café sur le papier
        for _ in range(6):
            cx, cy = rng.randrange(100, 1140), rng.randrange(100, 1650)
            rx, ry = rng.randrange(40, 140), rng.randrange(30, 110)
            draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=rng.randrange(195, 215))
    y = 80
    for line in _text_lines(spec, 0):
        draw.text((90, y), line, fill=70 if degraded else 30, font=font)
        y += 40
    for _ in range(12000 if degraded else 4000):
        draw.point((rng.randrange(1240), rng.randrange(1754)), fill=rng.randrange(120, 200))
    rotation, blur = (3.2, 1.4) if degraded else (1.5, 0.8)
    image = image.rotate(rotation, fillcolor=238 if degraded else 245).filter(ImageFilter.GaussianBlur(blur))
    image.save(path)


def generate(out_dir: Path = DATASET_DIR) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    specs = build_specs()
    for index, spec in enumerate(specs):
        path = out_dir / spec["file"]
        if spec.get("text"):
            render_text(spec["text"], path)
        elif path.suffix == ".png":
            render_scan(spec, path)
        elif spec.get("layout") == 2:
            render_table_pdf(spec, path)
        else:
            render_pdf(spec, path, layout=spec.get("layout", index % 2))
    documents = [{k: v for k, v in s.items() if k in ("file", "expected_status", "expected_issues", "accept", "invoice")}
                 for s in specs]
    (out_dir / "expected.json").write_text(
        json.dumps({"today": TODAY.isoformat(), "documents": documents}, ensure_ascii=False, indent=2)
    )
    return specs


if __name__ == "__main__":
    generated = generate()
    print(f"{len(generated)} documents générés dans {DATASET_DIR}")
