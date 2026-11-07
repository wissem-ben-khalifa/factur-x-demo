"""Task 4: several VAT rates and prices with more than 2 decimals."""

import io
from decimal import Decimal

import pytest
from lxml import etree
from pypdf import PdfReader

from facturx_demo.cii import build_cii_xml
from facturx_demo.model import InvoiceLine, compute_totals
from facturx_demo.pdf import generate, render_invoice_pdf
from facturx_demo.samples import load_sample
from facturx_demo.validators import run_kosit, run_mustang


def _pdf_text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


def _three_decimal_invoice():
    inv = load_sample("martin")
    line = InvoiceLine(
        description="Main d’œuvre au quart d’heure",
        quantity=Decimal("1.5"),
        unit_code="HUR",
        unit_price=Decimal("66.667"),
        vat_rate=Decimal("20"),
    )
    return inv.model_copy(update={"lines": [line]})


def test_multi_rate_breakdown():
    totals = compute_totals(load_sample("multi_rate"))
    by_rate = {v.rate: (v.basis, v.amount) for v in totals.vat}
    assert by_rate == {
        Decimal("20"): (Decimal("300.00"), Decimal("60.00")),
        Decimal("10"): (Decimal("99.99"), Decimal("10.00")),  # 9.999 rounds up, once per rate
    }
    assert totals.total_ht == Decimal("399.99")
    assert totals.total_vat == Decimal("70.00")
    assert totals.total_ttc == Decimal("469.99")


def test_multi_rate_xml_has_one_tax_block_per_rate():
    root = etree.fromstring(build_cii_xml(load_sample("multi_rate")))
    ns = {"ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"}
    blocks = root.xpath("//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax", namespaces=ns)
    found = {
        b.xpath("string(ram:RateApplicablePercent)", namespaces=ns): (
            b.xpath("string(ram:BasisAmount)", namespaces=ns),
            b.xpath("string(ram:CalculatedAmount)", namespaces=ns),
        )
        for b in blocks
    }
    assert len(blocks) == 2
    assert found == {"20": ("300.00", "60.00"), "10": ("99.99", "10.00")}


def test_three_decimal_price_rounds_line_net_once():
    inv = _three_decimal_invoice()
    totals = compute_totals(inv)
    assert totals.line_nets == [Decimal("100.00")]  # 1.5 x 66.667 = 100.0005
    xml = build_cii_xml(inv).decode("utf-8")
    assert "<ram:LineTotalAmount>100.00</ram:LineTotalAmount>" in xml
    assert "<ram:ChargeAmount>66.667</ram:ChargeAmount>" in xml


def test_three_decimal_price_is_shown_unrounded_in_pdf():
    text = _pdf_text(render_invoice_pdf(_three_decimal_invoice()))
    assert "66,667" in text  # the real unit price, not 66,67
    assert "100,00" in text


@pytest.mark.validators
def test_multi_rate_passes_kosit_and_mustang():
    inv = load_sample("multi_rate")
    pdf, xml = generate(inv)
    assert run_kosit(xml).ok
    assert run_mustang(pdf).ok


@pytest.mark.validators
def test_three_decimal_price_passes_kosit_and_mustang():
    pdf, xml = generate(_three_decimal_invoice())
    assert run_kosit(xml).ok
    assert run_mustang(pdf).ok
