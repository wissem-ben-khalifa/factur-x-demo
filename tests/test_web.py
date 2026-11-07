import pytest
from fastapi.testclient import TestClient

from facturx_demo import validators
from facturx_demo.samples import load_sample
from facturx_demo.web.app import app
from facturx_demo.web.forms import invoice_to_form

client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_docker_by_default(request, monkeypatch):
    """Keep web tests fast: pretend Docker is missing unless the test is marked `validators`."""
    if "validators" not in request.keywords:
        monkeypatch.setattr(validators, "docker_available", lambda: False)


def _martin_form() -> dict[str, str]:
    return invoice_to_form(load_sample("martin"))


def _post(data: dict[str, str]):
    return client.post("/generate", data=data)


def test_form_loads_sample():
    page = client.get("/", params={"sample": "martin"})
    assert page.status_code == 200
    assert "F-2027-0042" in page.text
    assert "Plomberie Martin" in page.text
    assert "000100008" in page.text


def test_blank_form_loads_with_default_legal_notes():
    page = client.get("/")
    assert page.status_code == 200
    assert "frais de recouvrement" in page.text


def test_generate_ok_returns_download_links():
    response = _post(_martin_form())
    assert response.status_code == 200
    assert "/factur-x.pdf" in response.text and "/factur-x.xml" in response.text
    link = next(w for w in response.text.split('"') if w.endswith("/factur-x.pdf"))
    pdf = client.get(link)
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    xml = client.get(link.replace("factur-x.pdf", "factur-x.xml"))
    assert xml.status_code == 200
    assert b"CrossIndustryInvoice" in xml.content


def test_generate_missing_siren_shows_french_and_english_message():
    data = _martin_form() | {"seller_siren": ""}
    response = _post(data)
    assert response.status_code == 422
    assert "Le numéro SIREN du vendeur est obligatoire" in response.text
    assert "The seller SIREN number is required" in response.text
    assert "Plomberie Martin" in response.text  # what the user typed is kept


def test_empty_form_shows_errors_not_500():
    response = _post({})
    assert response.status_code == 422
    assert "FORM-DATE-INVALID" in response.text


@pytest.mark.parametrize("bad", ["abc", "NaN", "Infinity", "1e999", "-0,5x"])
def test_bad_numbers_give_a_message_not_500(bad):
    data = _martin_form() | {"line_1_quantity": bad}
    response = _post(data)
    assert response.status_code == 422
    assert "Ligne 1" in response.text


def test_control_characters_and_html_are_handled():
    data = _martin_form() | {"buyer_name": "Café <script>alert(1)</script>\x00\x0b Le Soleil"}
    response = _post(data)
    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text


def test_too_long_text_is_rejected_with_a_message():
    response = _post(_martin_form() | {"seller_name": "x" * 5000})
    assert response.status_code == 422
    assert "FORM-TOO-LONG" in response.text


def test_comma_decimal_is_accepted():
    data = _martin_form() | {"line_1_unit_price": "80,00"}
    assert _post(data).status_code == 200


@pytest.mark.parametrize("bad_id", ["not-a-uuid", "..%2f..%2fetc", "0" * 36, "../x"])
def test_download_rejects_bad_id(bad_id):
    assert client.get(f"/download/{bad_id}/factur-x.pdf").status_code == 404


def test_download_unknown_valid_id_is_404():
    assert client.get("/download/123e4567-e89b-12d3-a456-426614174000/factur-x.pdf").status_code == 404


def test_download_rejects_other_filenames():
    response = _post(_martin_form())
    folder = next(w for w in response.text.split('"') if w.endswith("/factur-x.pdf")).rsplit("/", 1)[0]
    assert client.get(f"{folder}/secret.txt").status_code == 404


def test_validation_unavailable_message():
    response = _post(_martin_form())
    assert response.status_code == 200
    assert "Validation unavailable" in response.text or "Validation indisponible" in response.text


@pytest.mark.validators
def test_generate_with_docker_shows_both_validator_reports():
    response = _post(_martin_form())
    assert response.status_code == 200
    assert "KoSIT" in response.text and "Mustang" in response.text
    assert "Validation unavailable" not in response.text
