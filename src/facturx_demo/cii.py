"""Build the EN 16931 (Factur-X) CII XML with drafthorse."""

from decimal import Decimal

from drafthorse.models.accounting import ApplicableTradeTax
from drafthorse.models.document import Document
from drafthorse.models.party import TaxRegistration
from drafthorse.models.payment import PaymentTerms
from drafthorse.models.tradelines import LineItem

from facturx_demo.model import Invoice, Party, compute_totals

GUIDELINE_EN16931 = "urn:cen.eu:en16931:2017"
SIREN_SCHEME = "0002"  # ISO 6523 code for SIREN/SIRET
TYPE_CODE_INVOICE = "380"


def _fill_party(target, party: Party) -> None:
    target.name = party.name
    if party.siren:
        target.legal_organization.id = (SIREN_SCHEME, party.siren)
    target.address.line_one = party.street
    target.address.postcode = party.postcode
    target.address.city_name = party.city
    target.address.country_id = party.country
    if party.vat_id:
        reg = TaxRegistration()
        reg.id = ("VA", party.vat_id)
        target.tax_registrations.add(reg)


def build_cii_xml(inv: Invoice) -> bytes:
    totals = compute_totals(inv)
    doc = Document()
    doc.context.guideline_parameter.id = GUIDELINE_EN16931
    doc.header.id = inv.number
    doc.header.type_code = TYPE_CODE_INVOICE
    doc.header.issue_date_time = inv.issue_date

    for index, (line, net) in enumerate(zip(inv.lines, totals.line_nets), start=1):
        item = LineItem()
        item.document.line_id = str(index)
        item.product.name = line.description
        item.agreement.net.amount = line.unit_price
        item.delivery.billed_quantity = (line.quantity, line.unit_code)
        item.settlement.trade_tax.type_code = "VAT"
        item.settlement.trade_tax.category_code = "S"
        item.settlement.trade_tax.rate_applicable_percent = line.vat_rate
        item.settlement.monetary_summation.total_amount = net
        doc.trade.items.add(item)

    _fill_party(doc.trade.agreement.seller, inv.seller)
    _fill_party(doc.trade.agreement.buyer, inv.buyer)

    if inv.delivery_date:
        doc.trade.delivery.event.occurrence = inv.delivery_date

    settlement = doc.trade.settlement
    settlement.currency_code = inv.currency
    for breakdown in totals.vat:
        tax = ApplicableTradeTax()
        tax.calculated_amount = breakdown.amount
        tax.type_code = "VAT"
        tax.basis_amount = breakdown.basis
        tax.category_code = "S"
        tax.rate_applicable_percent = breakdown.rate
        settlement.trade_tax.add(tax)

    if inv.due_date or inv.payment_terms:
        terms = PaymentTerms()
        if inv.payment_terms:
            terms.description = inv.payment_terms
        if inv.due_date:
            terms.due = inv.due_date
        settlement.terms.add(terms)

    summ = settlement.monetary_summation
    summ.line_total = totals.total_ht
    summ.charge_total = Decimal("0.00")
    summ.allowance_total = Decimal("0.00")
    summ.tax_basis_total = (totals.total_ht, inv.currency)
    summ.tax_total = (totals.total_vat, inv.currency)
    summ.grand_total = (totals.total_ttc, inv.currency)
    summ.due_amount = totals.total_ttc

    return doc.serialize(schema="FACTUR-X_EN16931")
