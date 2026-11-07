from datetime import date
from decimal import Decimal

import pytest

from facturx_demo.checks import check_invoice
from facturx_demo.model import Invoice, InvoiceNote, Party
from facturx_demo.samples import load_sample


def _martin() -> Invoice:
    return load_sample("martin")


def _party(inv: Invoice, side: str, **changes) -> Invoice:
    party = getattr(inv, side).model_copy(update=changes)
    return inv.model_copy(update={side: party})


def _line(inv: Invoice, index: int, **changes) -> Invoice:
    lines = list(inv.lines)
    lines[index] = lines[index].model_copy(update=changes)
    return inv.model_copy(update={"lines": lines})


def _find(inv: Invoice, code: str):
    found = [i for i in check_invoice(inv) if i.code == code]
    assert found, f"{code} not reported: {[i.code for i in check_invoice(inv)]}"
    issue = found[0]
    assert issue.field
    assert issue.message_fr.strip()
    assert issue.message_en.strip()
    assert issue.message_fr != issue.message_en
    return issue


@pytest.mark.parametrize("name", ["martin", "multi_rate"])
def test_samples_have_no_issues(name):
    assert check_invoice(load_sample(name)) == []


def test_seller_siren_missing():
    assert _find(_party(_martin(), "seller", siren=None), "FR-SELLER-SIREN-MISSING").field == "seller.siren"


def test_buyer_siren_missing():
    assert _find(_party(_martin(), "buyer", siren=""), "FR-BUYER-SIREN-MISSING").field == "buyer.siren"


def test_siren_invalid_wrong_checksum_and_wrong_length():
    assert _find(_party(_martin(), "seller", siren="000100009"), "FR-SIREN-INVALID").field == "seller.siren"
    assert _find(_party(_martin(), "buyer", siren="12345"), "FR-SIREN-INVALID").field == "buyer.siren"


def test_vat_id_mismatch():
    assert _find(_party(_martin(), "seller", vat_id="FR00000100008"), "FR-VAT-ID-MISMATCH").field == "seller.vat_id"


def test_buyer_address_missing():
    inv = _party(_martin(), "buyer", street="", city="  ")
    assert _find(inv, "FR-BUYER-ADDRESS-MISSING").field == "buyer.address"


def test_legal_notes_missing_names_the_missing_codes():
    inv = _martin().model_copy(update={"notes": [n for n in _martin().notes if n.code != "AAB"]})
    issue = _find(inv, "FR-LEGAL-NOTES-MISSING")
    assert "AAB" in issue.message_en and "PMT" not in issue.message_en


def test_endpoint_missing():
    assert _find(_party(_martin(), "buyer", endpoint_id=None), "FR-ENDPOINT-MISSING").field == "buyer.endpoint_id"


def test_no_lines():
    assert _find(_martin().model_copy(update={"lines": []}), "INV-NO-LINES").field == "lines"


@pytest.mark.parametrize("qty", ["0", "-2"])
def test_quantity_not_positive(qty):
    assert _find(_line(_martin(), 1, quantity=Decimal(qty)), "INV-QTY-NOT-POSITIVE").field == "lines[2].quantity"


def test_price_negative():
    assert _find(_line(_martin(), 0, unit_price=Decimal("-1")), "INV-PRICE-NEGATIVE").field == "lines[1].unit_price"


def test_vat_rate_unknown():
    assert _find(_line(_martin(), 0, vat_rate=Decimal("19")), "INV-VAT-RATE-UNKNOWN").field == "lines[1].vat_rate"


def test_due_before_issue():
    inv = _martin().model_copy(update={"due_date": date(2027, 9, 1)})
    assert _find(inv, "INV-DUE-BEFORE-ISSUE").field == "due_date"


def test_blank_invoice_gives_issues_not_an_exception():
    blank = Invoice(
        number="",
        issue_date=date(2027, 9, 15),
        seller=Party(name="", street="", postcode="", city=""),
        buyer=Party(name="", street="", postcode="", city=""),
        lines=[],
        operation_category="services",
        notes=[],
    )
    codes = {i.code for i in check_invoice(blank)}
    assert {"FR-SELLER-SIREN-MISSING", "FR-BUYER-SIREN-MISSING", "INV-NO-LINES", "FR-LEGAL-NOTES-MISSING"} <= codes
    assert "INV-NUMBER-MISSING" in codes


def test_note_text_is_required():
    inv = _martin().model_copy(update={"notes": [InvoiceNote(code="PMT", text=" "), *_martin().notes[1:]]})
    assert "FR-LEGAL-NOTES-MISSING" in {i.code for i in check_invoice(inv)}
