"""Mandatory mentions added in Task 8: delivery address (if different) and VAT-on-debits option."""

import io

import pytest
from fastapi.testclient import TestClient
from lxml import etree
from pypdf import PdfReader

from facturx_demo import validators
from facturx_demo.checks import check_invoice
from facturx_demo.cii import build_cii_xml
from facturx_demo.model import DeliveryAddress, Invoice, effective_delivery_address
from facturx_demo.pdf import generate, render_invoice_pdf
from facturx_demo.samples import load_sample
from facturx_demo.validators import run_kosit, run_mustang
from facturx_demo.web.app import app
from facturx_demo.web.forms import invoice_to_form, parse_form

NS = {"ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"}
SITE = DeliveryAddress(name="Chantier Les Tilleuls", street="4 chemin des Vignes", postcode="69130", city="Écully")


def _martin(**changes) -> Invoice:
    return load_sample("martin").model_copy(update=changes)


def _xml(inv: Invoice):
    return etree.fromstring(build_cii_xml(inv))


def _pdf_text(inv: Invoice) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(render_invoice_pdf(inv))).pages)


# ---- delivery address -------------------------------------------------------------------------


def test_no_delivery_address_by_default():
    inv = load_sample("martin")
    assert inv.delivery_address is None
    assert _xml(inv).xpath("//ram:ShipToTradeParty", namespaces=NS) == []
    assert "Adresse de livraison" not in _pdf_text(inv)


def test_delivery_address_in_xml():
    root = _xml(_martin(delivery_address=SITE))
    ship = root.xpath("//ram:ApplicableHeaderTradeDelivery/ram:ShipToTradeParty", namespaces=NS)
    assert len(ship) == 1

    def value(tag):
        return ship[0].xpath(f"string(.//ram:{tag})", namespaces=NS)

    assert value("Name") == "Chantier Les Tilleuls"
    assert value("LineOne") == "4 chemin des Vignes"
    assert value("PostcodeCode") == "69130"
    assert value("CityName") == "Écully"
    assert value("CountryID") == "FR"


def test_delivery_address_in_pdf():
    text = _pdf_text(_martin(delivery_address=SITE))
    assert "Adresse de livraison" in text
    assert "4 chemin des Vignes" in text and "69130 Écully" in text


def test_delivery_address_same_as_buyer_is_not_sent():
    buyer = load_sample("martin").buyer
    same = DeliveryAddress(
        street=buyer.street.upper() + "  ", postcode=buyer.postcode, city=buyer.city.lower()
    )
    inv = _martin(delivery_address=same)
    assert effective_delivery_address(inv) is None
    assert _xml(inv).xpath("//ram:ShipToTradeParty", namespaces=NS) == []
    assert "Adresse de livraison" not in _pdf_text(inv)


def test_effective_delivery_address_keeps_a_different_one():
    assert effective_delivery_address(_martin(delivery_address=SITE)) == SITE


def test_delivery_address_incomplete():
    inv = _martin(delivery_address=SITE.model_copy(update={"street": " ", "city": ""}))
    issue = next(i for i in check_invoice(inv) if i.code == "FR-DELIVERY-ADDRESS-INCOMPLETE")
    assert issue.field == "delivery_address"
    assert issue.message_fr.strip() and issue.message_en.strip() and issue.message_fr != issue.message_en


@pytest.mark.parametrize("country", ["", "F", "FRA", "fr", "F1"])
def test_delivery_country_invalid(country):
    inv = _martin(delivery_address=SITE.model_copy(update={"country": country}))
    issue = next(i for i in check_invoice(inv) if i.code == "FR-DELIVERY-COUNTRY-INVALID")
    assert issue.field == "delivery_address.country"


def test_complete_delivery_address_has_no_issue():
    assert check_invoice(_martin(delivery_address=SITE)) == []


# ---- VAT on debits ----------------------------------------------------------------------------


def test_vat_on_debits_off_by_default():
    inv = load_sample("martin")
    assert inv.vat_on_debits is False
    assert _xml(inv).xpath("//ram:DueDateTypeCode", namespaces=NS) == []
    assert "d’après les débits" not in _pdf_text(inv)


def test_vat_on_debits_sets_bt8_on_every_vat_breakdown():
    inv = load_sample("multi_rate").model_copy(update={"vat_on_debits": True})
    root = _xml(inv)
    breakdowns = root.xpath("//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax", namespaces=NS)
    assert len(breakdowns) == 2
    assert [b.xpath("string(ram:DueDateTypeCode)", namespaces=NS) for b in breakdowns] == ["5", "5"]


def test_vat_on_debits_in_pdf():
    text = _pdf_text(_martin(vat_on_debits=True))
    assert "Option pour le paiement de la TVA d’après les débits" in text


# ---- samples, form round trip, web ------------------------------------------------------------


def test_multi_rate_sample_uses_both_mentions():
    inv = load_sample("multi_rate")
    assert effective_delivery_address(inv) is not None
    assert inv.vat_on_debits is True


@pytest.mark.parametrize("name", ["martin", "multi_rate"])
def test_form_round_trip_keeps_everything(name):
    inv = load_sample(name)
    parsed, issues = parse_form(invoice_to_form(inv))
    assert issues == []
    assert parsed == inv


def test_form_blank_delivery_fields_mean_no_delivery_address():
    form = invoice_to_form(load_sample("martin"))
    assert form["delivery_street"] == "" and form["delivery_country"] == "FR"
    parsed, issues = parse_form(form)
    assert issues == [] and parsed.delivery_address is None


def test_form_partial_delivery_address_is_reported():
    form = invoice_to_form(load_sample("martin")) | {"delivery_city": "Écully"}
    parsed, issues = parse_form(form)
    assert issues == []  # reading the form works; the checks report what is missing
    assert "FR-DELIVERY-ADDRESS-INCOMPLETE" in {i.code for i in check_invoice(parsed)}


def test_form_country_is_uppercased_and_checkbox_is_read():
    form = invoice_to_form(load_sample("martin")) | {
        "delivery_street": "4 chemin des Vignes",
        "delivery_postcode": "69130",
        "delivery_city": "Écully",
        "delivery_country": "fr",
        "vat_on_debits": "on",
    }
    parsed, _ = parse_form(form)
    assert parsed.delivery_address.country == "FR"
    assert parsed.vat_on_debits is True


@pytest.fixture
def _no_docker(monkeypatch):
    monkeypatch.setattr(validators, "docker_available", lambda: False)


def test_web_generates_both_mentions(_no_docker):
    client = TestClient(app)
    form = invoice_to_form(load_sample("martin")) | {
        "delivery_name": "Chantier Les Tilleuls",
        "delivery_street": "4 chemin des Vignes",
        "delivery_postcode": "69130",
        "delivery_city": "Écully",
        "vat_on_debits": "on",
    }
    response = client.post("/generate", data=form)
    assert response.status_code == 200
    link = next(w for w in response.text.split('"') if w.endswith("/factur-x.xml"))
    xml = client.get(link).content.decode("utf-8")
    assert "<ram:ShipToTradeParty>" in xml and "4 chemin des Vignes" in xml
    assert "<ram:DueDateTypeCode>5</ram:DueDateTypeCode>" in xml


def test_web_partial_delivery_address_gives_422(_no_docker):
    client = TestClient(app)
    form = invoice_to_form(load_sample("martin")) | {"delivery_city": "Écully"}
    response = client.post("/generate", data=form)
    assert response.status_code == 422
    assert "FR-DELIVERY-ADDRESS-INCOMPLETE" in response.text
    assert "adresse de livraison" in response.text.lower()


def test_web_form_shows_the_new_fields(_no_docker):
    page = TestClient(app).get("/", params={"sample": "multi_rate"}).text
    assert 'name="delivery_street"' in page and 'name="vat_on_debits"' in page
    assert "checked" in page  # multi_rate has the debit option on


# ---- official validators ----------------------------------------------------------------------


@pytest.mark.validators
def test_delivery_address_and_debits_pass_kosit_and_mustang():
    inv = _martin(delivery_address=SITE, vat_on_debits=True)
    pdf, xml = generate(inv)
    for report in (run_kosit(xml), run_mustang(pdf)):
        assert report.ok, report.findings
        assert report.findings == []


@pytest.mark.validators
def test_foreign_delivery_address_passes_validators():
    inv = _martin(delivery_address=SITE.model_copy(update={"country": "BE", "postcode": "1000", "city": "Bruxelles"}))
    pdf, xml = generate(inv)
    assert run_kosit(xml).ok
    assert run_mustang(pdf).ok
