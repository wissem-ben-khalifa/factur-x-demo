"""Build the EN 16931 (Factur-X) CII XML with drafthorse."""

from decimal import Decimal

from drafthorse.models.accounting import ApplicableTradeTax
from drafthorse.models.document import Document
from drafthorse.models.note import IncludedNote
from drafthorse.models.party import TaxRegistration
from drafthorse.models.payment import PaymentTerms
from drafthorse.models.tradelines import LineItem

from facturx_demo.model import Invoice, Party, compute_totals, effective_delivery_address

GUIDELINE_EN16931 = "urn:cen.eu:en16931:2017"
SIREN_SCHEME = "0002"  # ISO 6523 code for SIREN/SIRET
ENDPOINT_SCHEME = "0225"  # French electronic address scheme named in rule BR-FR-23
TYPE_CODE_INVOICE = "380"
# BT-23 "cadre de facturation" (DGFiP table: nature of the operation). Letter = goods / services /
# both; digit 1 = plain invoice to be paid. Allowed values are listed in rule BR-FR-08.
BILLING_FRAMEWORK = {"goods": "B1", "services": "S1", "mixed": "M1"}
VAT_ON_DEBITS_CODE = "5"  # BT-8 in CII: VAT due at invoice issue (option for payment on debits)


def _fill_party(target, party: Party) -> None:
    target.name = party.name
    if party.siren:
        target.legal_organization.id = (SIREN_SCHEME, party.siren)
    target.address.line_one = party.street
    target.address.postcode = party.postcode
    target.address.city_name = party.city
    target.address.country_id = party.country
    if party.endpoint_id:
        target.electronic_address.uri_ID = (ENDPOINT_SCHEME, party.endpoint_id)
    if party.vat_id:
        reg = TaxRegistration()
        reg.id = ("VA", party.vat_id)
        target.tax_registrations.add(reg)


def build_cii_xml(inv: Invoice) -> bytes:
    totals = compute_totals(inv)
    doc = Document()
    doc.context.business_parameter.id = BILLING_FRAMEWORK[inv.operation_category]
    doc.context.guideline_parameter.id = GUIDELINE_EN16931
    doc.header.id = inv.number
    doc.header.type_code = TYPE_CODE_INVOICE
    doc.header.issue_date_time = inv.issue_date
    for note in inv.notes:
        included = IncludedNote()
        included.content = note.text
        included.subject_code = note.code
        doc.header.notes.add(included)

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
    delivery = effective_delivery_address(inv)
    if delivery is not None:
        ship_to = doc.trade.delivery.ship_to
        if delivery.name:
            ship_to.name = delivery.name
        ship_to.address.line_one = delivery.street
        ship_to.address.postcode = delivery.postcode
        ship_to.address.city_name = delivery.city
        ship_to.address.country_id = delivery.country

    settlement = doc.trade.settlement
    settlement.currency_code = inv.currency
    for breakdown in totals.vat:
        tax = ApplicableTradeTax()
        tax.calculated_amount = breakdown.amount
        tax.type_code = "VAT"
        tax.basis_amount = breakdown.basis
        tax.category_code = "S"
        tax.rate_applicable_percent = breakdown.rate
        if inv.vat_on_debits:
            tax.due_date_type_code = VAT_ON_DEBITS_CODE
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
    # EN 16931 (CII-DT-031): currencyID only on TaxTotalAmount, not on the other totals.
    summ.tax_basis_total = totals.total_ht
    summ.tax_total = (totals.total_vat, inv.currency)
    summ.grand_total = totals.total_ttc
    summ.due_amount = totals.total_ttc

    return doc.serialize(schema="FACTUR-X_EN16931")
