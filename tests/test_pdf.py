import io

import facturx
import pytest
from pypdf import PdfReader

from facturx_demo.cii import build_cii_xml
from facturx_demo.pdf import generate, render_invoice_pdf
from facturx_demo.samples import load_sample
from facturx_demo.validators import run_mustang


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


def test_visual_pdf_shows_mentions():
    inv = load_sample("martin")
    text = _text(render_invoice_pdf(inv))
    assert inv.number in text
    assert inv.seller.siren in text
    assert inv.buyer.siren in text
    assert "360,00" in text
    assert "Main d’œuvre" in text


def test_facturx_has_embedded_xml():
    inv = load_sample("martin")
    pdf, xml = generate(inv)
    assert xml == build_cii_xml(inv)
    filename, embedded = facturx.get_xml_from_pdf(pdf)
    assert filename == "factur-x.xml"
    assert embedded == xml


@pytest.mark.validators
def test_mustang_accepts_martin_pdf():
    pdf, _ = generate(load_sample("martin"))
    report = run_mustang(pdf)
    assert report.ok, [f for f in report.findings if f.severity == "error"]
    assert [f for f in report.findings if f.severity == "error"] == []


@pytest.mark.validators
def test_mustang_flags_a_plain_pdf_as_not_pdfa():
    """Guards the test above: Mustang must really look at PDF/A, not just the XML."""
    report = run_mustang(render_invoice_pdf(load_sample("martin")))
    assert not report.ok
    assert any(f.rule_id.startswith("PDFA-") for f in report.findings)
