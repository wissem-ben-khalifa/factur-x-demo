"""Invoice data model and totals. All money is Decimal, never float."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    """Round to 2 decimals, half up (the usual commercial rule)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


class Party(BaseModel):
    name: str
    siren: str | None = None
    vat_id: str | None = None
    street: str
    postcode: str
    city: str
    country: str = "FR"
    email: str | None = None
    # French electronic address (BT-34 seller / BT-49 buyer), scheme 0225. In real life the
    # approved platform assigns it; here it is a fictional value.
    endpoint_id: str | None = None


class InvoiceLine(BaseModel):
    description: str
    quantity: Decimal
    unit_code: str  # HUR = hours, C62 = unit
    unit_price: Decimal  # excl. VAT
    vat_rate: Decimal  # percent, e.g. 20


class InvoiceNote(BaseModel):
    """Mandatory French legal note (BR-FR-05): PMT recovery fees, PMD late penalties, AAB discount."""

    code: Literal["PMT", "PMD", "AAB"]
    text: str


REQUIRED_NOTE_CODES = ("PMT", "PMD", "AAB")


class DeliveryAddress(BaseModel):
    """Where the goods are delivered, when different from the buyer's address (BG-13, BG-15)."""

    name: str | None = None
    street: str
    postcode: str
    city: str
    country: str = "FR"


class Invoice(BaseModel):
    number: str
    issue_date: date
    due_date: date | None = None
    delivery_date: date | None = None
    currency: str = "EUR"
    seller: Party
    buyer: Party
    lines: list[InvoiceLine]
    operation_category: Literal["goods", "services", "mixed"]
    payment_terms: str | None = None
    notes: list[InvoiceNote] = []
    delivery_address: DeliveryAddress | None = None
    # Seller opted to pay VAT on debits: VAT is due when the invoice is issued (BT-8 code 5 in CII).
    vat_on_debits: bool = False


class VatBreakdown(BaseModel):
    rate: Decimal
    basis: Decimal
    amount: Decimal


class Totals(BaseModel):
    line_nets: list[Decimal]
    vat: list[VatBreakdown]
    total_ht: Decimal
    total_vat: Decimal
    total_ttc: Decimal


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def effective_delivery_address(inv: Invoice) -> DeliveryAddress | None:
    """The delivery address to print and send: None when absent or equal to the buyer's address."""
    d, b = inv.delivery_address, inv.buyer
    if d is None:
        return None
    if (
        _same(d.street, b.street)
        and _same(d.postcode, b.postcode)
        and _same(d.city, b.city)
        and _same(d.country, b.country)
    ):
        return None
    return d


def compute_totals(inv: Invoice) -> Totals:
    """Line net = qty x price rounded to cents; VAT rounded once per rate."""
    line_nets = [money(line.quantity * line.unit_price) for line in inv.lines]
    basis_by_rate: dict[Decimal, Decimal] = {}
    for line, net in zip(inv.lines, line_nets):
        basis_by_rate[line.vat_rate] = basis_by_rate.get(line.vat_rate, Decimal("0")) + net
    vat = [
        VatBreakdown(rate=rate, basis=basis, amount=money(basis * rate / 100))
        for rate, basis in sorted(basis_by_rate.items(), reverse=True)
    ]
    total_ht = sum(line_nets, Decimal("0.00"))
    total_vat = sum((v.amount for v in vat), Decimal("0.00"))
    return Totals(
        line_nets=line_nets,
        vat=vat,
        total_ht=total_ht,
        total_vat=total_vat,
        total_ttc=total_ht + total_vat,
    )
