"""Turn the HTML form into an Invoice (and back). Bad input becomes Issues, never exceptions."""

import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation

from facturx_demo.checks import Issue
from facturx_demo.model import Invoice, InvoiceLine, InvoiceNote, Party

LINE_COUNT = 5
MAX_TEXT = 300
MAX_NOTE = 600
MAX_NUMBER = Decimal("1000000000")
# Control characters are not allowed in XML 1.0 (tab, newline and carriage return are).
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

PARTY_FIELDS = ("name", "siren", "vat_id", "street", "postcode", "city", "endpoint_id")
LINE_FIELDS = ("description", "quantity", "unit_code", "unit_price", "vat_rate")

DEFAULT_NOTES = {
    "PMT": "Indemnité forfaitaire pour frais de recouvrement en cas de retard de paiement : 40 €.",
    "PMD": "En cas de retard de paiement, une pénalité égale à trois fois le taux d’intérêt légal sera appliquée.",
    "AAB": "Pas d’escompte pour paiement anticipé.",
}


def blank_form() -> dict[str, str]:
    form = {"operation_category": "services", "payment_terms": "Paiement à 30 jours"}
    for i in range(1, LINE_COUNT + 1):
        form[f"line_{i}_unit_code"] = "HUR" if i == 1 else "C62"
        form[f"line_{i}_vat_rate"] = "20"
    for code, text in DEFAULT_NOTES.items():
        form[f"note_{code}"] = text
    return form


def invoice_to_form(inv: Invoice) -> dict[str, str]:
    """Flat form values for an invoice (used to pre-fill the page from a sample)."""
    form = blank_form()
    form |= {
        "number": inv.number,
        "issue_date": inv.issue_date.isoformat(),
        "due_date": inv.due_date.isoformat() if inv.due_date else "",
        "delivery_date": inv.delivery_date.isoformat() if inv.delivery_date else "",
        "operation_category": inv.operation_category,
        "payment_terms": inv.payment_terms or "",
    }
    for side in ("seller", "buyer"):
        party = getattr(inv, side)
        for field in PARTY_FIELDS:
            form[f"{side}_{field}"] = getattr(party, field) or ""
    for i in range(1, LINE_COUNT + 1):
        line = inv.lines[i - 1] if i <= len(inv.lines) else None
        form[f"line_{i}_description"] = line.description if line else ""
        form[f"line_{i}_quantity"] = f"{line.quantity:f}" if line else ""
        form[f"line_{i}_unit_code"] = line.unit_code if line else form[f"line_{i}_unit_code"]
        form[f"line_{i}_unit_price"] = f"{line.unit_price:f}" if line else ""
        form[f"line_{i}_vat_rate"] = f"{line.vat_rate:f}" if line else "20"
    for code in DEFAULT_NOTES:
        form[f"note_{code}"] = ""
    for note in inv.notes:
        form[f"note_{note.code}"] = note.text
    return form


class _Parser:
    def __init__(self, data: Mapping[str, str]):
        self.data = data
        self.issues: list[Issue] = []
        self._seen: dict[str, str] = {}

    def _problem(self, code: str, field: str, fr: str, en: str) -> None:
        self.issues.append(Issue(code=code, field=field, message_fr=fr, message_en=en))

    def text(self, key: str, limit: int = MAX_TEXT) -> str:
        """Cleaned single-line text; each field is read (and reported) only once."""
        if key not in self._seen:
            self._seen[key] = self._clean(key, limit)
        return self._seen[key]

    def _clean(self, key: str, limit: int) -> str:
        raw = self.data.get(key, "") or ""
        if len(raw) > limit:
            self._problem(
                "FORM-TOO-LONG", key,
                f"Le champ « {key} » est trop long (maximum {limit} caractères).",
                f"The field \"{key}\" is too long (maximum {limit} characters).",
            )  # fmt: skip
            raw = raw[:limit]
        return " ".join(_CONTROL.sub("", raw).split())

    def date(self, key: str, required: bool, label_fr: str, label_en: str) -> date | None:
        value = self.text(key)
        if not value:
            if required:
                self._problem(
                    "FORM-DATE-INVALID", key,
                    f"{label_fr} : date obligatoire (AAAA-MM-JJ).",
                    f"{label_en}: a date is required (YYYY-MM-DD).",
                )  # fmt: skip
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            self._problem(
                "FORM-DATE-INVALID", key,
                f"{label_fr} : date invalide « {value} » (format AAAA-MM-JJ).",
                f"{label_en}: invalid date \"{value}\" (format YYYY-MM-DD).",
            )  # fmt: skip
            return None

    def number(self, key: str, line: int, label_fr: str, label_en: str) -> Decimal | None:
        value = self.text(key).replace(",", ".")
        problem = (
            f"Ligne {line} : {label_fr} invalide « {value} ».",
            f"Line {line}: invalid {label_en} \"{value}\".",
        )
        try:
            number = Decimal(value)
        except InvalidOperation:
            self._problem("FORM-NUMBER-INVALID", key, *problem)
            return None
        if not number.is_finite():
            self._problem("FORM-NUMBER-INVALID", key, *problem)
            return None
        if abs(number) >= MAX_NUMBER:
            self._problem(
                "FORM-NUMBER-TOO-BIG", key,
                f"Ligne {line} : {label_fr} trop grand(e).",
                f"Line {line}: {label_en} is too large.",
            )  # fmt: skip
            return None
        return number


def parse_form(data: Mapping[str, str]) -> tuple[Invoice | None, list[Issue]]:
    """Return (invoice, issues). The invoice is None when the form cannot be read at all."""
    p = _Parser(data)

    issue_date = p.date("issue_date", True, "Date d’émission", "Issue date")
    due_date = p.date("due_date", False, "Date d’échéance", "Due date")
    delivery_date = p.date("delivery_date", False, "Date de livraison", "Delivery date")

    parties: dict[str, Party] = {}
    for side in ("seller", "buyer"):
        values = {f: p.text(f"{side}_{f}") for f in PARTY_FIELDS}
        parties[side] = Party(
            name=values["name"],
            siren=values["siren"] or None,
            vat_id=values["vat_id"] or None,
            street=values["street"],
            postcode=values["postcode"],
            city=values["city"],
            endpoint_id=values["endpoint_id"] or None,
        )

    lines: list[InvoiceLine] = []
    for i in range(1, LINE_COUNT + 1):
        keys = {f: f"line_{i}_{f}" for f in LINE_FIELDS}
        if not any(p.text(keys[f]) for f in ("description", "quantity", "unit_price")):
            continue  # empty row
        quantity = p.number(keys["quantity"], i, "quantité", "quantity")
        price = p.number(keys["unit_price"], i, "prix unitaire", "unit price")
        rate = p.number(keys["vat_rate"], i, "taux de TVA", "VAT rate")
        unit_code = p.text(keys["unit_code"])
        if unit_code not in ("HUR", "C62"):
            unit_code = "C62"
        if None in (quantity, price, rate):
            continue
        lines.append(
            InvoiceLine(
                description=p.text(keys["description"]),
                quantity=quantity,
                unit_code=unit_code,
                unit_price=price,
                vat_rate=rate,
            )
        )

    category = p.text("operation_category") or "services"
    if category not in ("goods", "services", "mixed"):
        p._problem(
            "FORM-CATEGORY-INVALID", "operation_category",
            "Nature de l’opération invalide.", "Invalid nature of the operation.",
        )  # fmt: skip
        category = "services"

    notes = [
        InvoiceNote(code=code, text=p.text(f"note_{code}", MAX_NOTE))
        for code in DEFAULT_NOTES
        if p.text(f"note_{code}", MAX_NOTE)
    ]

    if issue_date is None:
        return None, p.issues
    invoice = Invoice(
        number=p.text("number"),
        issue_date=issue_date,
        due_date=due_date,
        delivery_date=delivery_date,
        seller=parties["seller"],
        buyer=parties["buyer"],
        lines=lines,
        operation_category=category,
        payment_terms=p.text("payment_terms") or None,
        notes=notes,
    )
    return invoice, p.issues
