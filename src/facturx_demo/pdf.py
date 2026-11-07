"""Visual invoice PDF (fpdf2) and Factur-X packaging (PDF/A-3 with the XML embedded)."""

from decimal import Decimal
from pathlib import Path

import facturx
from fpdf import FPDF
from fpdf.enums import OutputIntentSubType
from fpdf.output import PDFICCProfile
from PIL import ImageCms

from facturx_demo.cii import build_cii_xml
from facturx_demo.model import Invoice, Party, compute_totals

FONTS = Path(__file__).parent / "fonts"
FONT = "DejaVu"

CATEGORY_FR = {"goods": "Livraison de biens", "services": "Prestation de services", "mixed": "Biens et services"}
UNIT_FR = {"HUR": "h", "C62": "u"}


def _srgb_profile() -> bytes:
    """Built-in sRGB ICC profile (from Pillow/LittleCMS), used as the PDF/A OutputIntent."""
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def fr_number(value: Decimal) -> str:
    """360.5 -> '360,50' (French decimal comma, space as thousands separator)."""
    text = f"{value:,.2f}"
    return text.replace(",", " ").replace(".", ",")


def fr_price(value: Decimal) -> str:
    """Unit price with its real decimals (at least 2): 66.667 -> '66,667', 80 -> '80,00'."""
    exponent = value.normalize().as_tuple().exponent
    places = max(2, -exponent if isinstance(exponent, int) else 2)
    text = f"{value:,.{places}f}"
    return text.replace(",", " ").replace(".", ",")


def fr_date(d) -> str:
    return d.strftime("%d/%m/%Y")


def _party_block(pdf: FPDF, title: str, party: Party, x: float, width: float) -> None:
    pdf.set_xy(x, pdf.get_y())
    pdf.set_font(FONT, "B", 9)
    pdf.cell(width, 5, title, new_x="LEFT", new_y="NEXT")
    pdf.set_font(FONT, "B", 11)
    pdf.cell(width, 6, party.name, new_x="LEFT", new_y="NEXT")
    pdf.set_font(FONT, "", 9)
    lines = [party.street, f"{party.postcode} {party.city}"]
    if party.siren:
        lines.append(f"SIREN : {party.siren}")
    if party.vat_id:
        lines.append(f"TVA : {party.vat_id}")
    for line in lines:
        pdf.set_x(x)
        pdf.cell(width, 4.5, line, new_x="LEFT", new_y="NEXT")


def render_invoice_pdf(inv: Invoice) -> bytes:
    """Draw the human-readable invoice. Fonts are embedded (needed for PDF/A)."""
    totals = compute_totals(inv)
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_font(FONT, "", str(FONTS / "DejaVuSans.ttf"))
    pdf.add_font(FONT, "B", str(FONTS / "DejaVuSans-Bold.ttf"))
    pdf.set_title(f"Facture {inv.number}")
    pdf.set_author(inv.seller.name)
    pdf.set_creator("factur-x-demo")
    # PDF/A needs an OutputIntent whenever DeviceRGB/DeviceGray colours are used.
    pdf.add_output_intent(
        OutputIntentSubType.PDFA,
        output_condition_identifier="sRGB IEC61966-2.1",
        output_condition="sRGB IEC61966-2.1",
        registry_name="http://www.color.org",
        dest_output_profile=PDFICCProfile(contents=_srgb_profile(), n=3, alternate="DeviceRGB"),
        info="sRGB IEC61966-2.1",
    )
    pdf.set_lang("fr-FR")
    pdf.add_page()

    pdf.set_font(FONT, "B", 18)
    pdf.cell(0, 10, "FACTURE", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FONT, "", 10)
    pdf.cell(0, 5, f"N° {inv.number}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, f"Date d’émission : {fr_date(inv.issue_date)}", new_x="LMARGIN", new_y="NEXT")
    if inv.delivery_date:
        pdf.cell(0, 5, f"Date de livraison / exécution : {fr_date(inv.delivery_date)}", new_x="LMARGIN", new_y="NEXT")
    if inv.due_date:
        pdf.cell(0, 5, f"Échéance : {fr_date(inv.due_date)}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, f"Nature de l’opération : {CATEGORY_FR[inv.operation_category]}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    top = pdf.get_y()
    _party_block(pdf, "Vendeur", inv.seller, 10, 90)
    after_seller = pdf.get_y()
    pdf.set_y(top)
    _party_block(pdf, "Client", inv.buyer, 110, 90)
    pdf.set_y(max(after_seller, pdf.get_y()) + 8)

    # Lines table
    widths = [88, 22, 28, 20, 32]
    heads = ["Désignation", "Quantité", "Prix unit. HT", "TVA", "Total HT"]
    pdf.set_font(FONT, "B", 9)
    pdf.set_fill_color(230, 230, 230)
    for w, h in zip(widths, heads):
        pdf.cell(w, 7, h, border=1, fill=True, align="L" if h == "Désignation" else "R")
    pdf.ln()
    pdf.set_font(FONT, "", 9)
    for line, net in zip(inv.lines, totals.line_nets):
        qty = f"{line.quantity.normalize():f} {UNIT_FR.get(line.unit_code, line.unit_code)}"
        cells = [line.description, qty, fr_price(line.unit_price), f"{line.vat_rate.normalize():f} %", fr_number(net)]
        for w, text, head in zip(widths, cells, heads):
            pdf.cell(w, 7, text, border=1, align="L" if head == "Désignation" else "R")
        pdf.ln()
    pdf.ln(4)

    # VAT breakdown and totals
    pdf.set_font(FONT, "", 9)
    for v in totals.vat:
        pdf.cell(0, 5, f"TVA {v.rate.normalize():f} % sur {fr_number(v.basis)} € : {fr_number(v.amount)} €", new_x="LMARGIN", new_y="NEXT", align="R")
    pdf.ln(2)
    pdf.cell(0, 5, f"Total HT : {fr_number(totals.total_ht)} €", new_x="LMARGIN", new_y="NEXT", align="R")
    pdf.cell(0, 5, f"Total TVA : {fr_number(totals.total_vat)} €", new_x="LMARGIN", new_y="NEXT", align="R")
    pdf.set_font(FONT, "B", 11)
    pdf.cell(0, 7, f"Total TTC : {fr_number(totals.total_ttc)} €", new_x="LMARGIN", new_y="NEXT", align="R")
    pdf.ln(6)
    pdf.set_font(FONT, "", 9)
    if inv.payment_terms:
        pdf.cell(0, 5, inv.payment_terms, new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())


def make_facturx(pdf: bytes, xml: bytes) -> bytes:
    """Embed the XML in the PDF and add the Factur-X / PDF/A-3 metadata."""
    return facturx.generate_from_binary(pdf, xml, flavor="factur-x", level="en16931")


def generate(inv: Invoice) -> tuple[bytes, bytes]:
    """Return (facturx_pdf, xml) for an invoice."""
    xml = build_cii_xml(inv)
    return make_facturx(render_invoice_pdf(inv), xml), xml
