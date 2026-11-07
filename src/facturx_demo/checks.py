"""Input checks with clear bilingual messages, run BEFORE generating a file.

Sources (checked 2026-11-07):
- Official list of new mandatory invoice mentions (buyer SIREN, nature of the operation, delivery
  address if different, VAT-on-debits option): economie.gouv.fr,
  https://www.economie.gouv.fr/entreprises/gerer-son-entreprise-au-quotidien/gerer-sa-comptabilite-et-ses-demarches/mentions-obligatoires-dune-facture-tout-savoir
  (found by web search; the pages disagree on the start date for SMEs, 1 Sept 2026 vs 2027).
- French e-invoicing rules BR-FR (Flux 2 schematron V1.3.0, 16 Feb 2026), bundled in Mustang 2.26.0:
  BR-FR-05 (notes PMT, PMD, AAB), BR-FR-10/11 (SIREN), BR-FR-12/13 (electronic addresses),
  BR-FR-CO-07 (due date), BR-FR-16 (allowed VAT rates).
Delivery address (when different) is checked for completeness; the VAT-on-debits option is a
yes/no choice of the seller, mapped to BT-8 (DGFiP data table + Vertex reference, Nov 2026).
"""

import re
from decimal import Decimal

from pydantic import BaseModel
from stdnum.fr import siren as siren_check

from facturx_demo.model import REQUIRED_NOTE_CODES, Invoice, Party

# The official BR-FR-16 list is wider (overseas and Corsica rates, 0 %). The demo supports four.
SUPPORTED_VAT_RATES = (Decimal("20"), Decimal("10"), Decimal("5.5"), Decimal("2.1"))


# note code -> (French label, English label)
NOTE_LABELS = {
    "PMT": ("PMT (frais de recouvrement)", "PMT (recovery fees)"),
    "PMD": ("PMD (pénalités de retard)", "PMD (late-payment penalties)"),
    "AAB": ("AAB (escompte)", "AAB (discount terms)"),
}


class Issue(BaseModel):
    code: str
    field: str
    message_fr: str
    message_en: str


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _expected_vat_id(siren: str) -> str:
    key = (12 + 3 * (int(siren) % 97)) % 97
    return f"FR{key:02d}{siren}"


def _check_party(party: Party, side: str, label_fr: str, label_en: str) -> list[Issue]:
    issues: list[Issue] = []
    if _blank(party.siren):
        issues.append(
            Issue(
                code=f"FR-{side.upper()}-SIREN-MISSING",
                field=f"{side}.siren",
                message_fr=f"Le numéro SIREN {label_fr} est obligatoire.",
                message_en=f"The {label_en} SIREN number is required.",
            )
        )
    elif not (party.siren.isdigit() and len(party.siren) == 9 and siren_check.is_valid(party.siren)):
        issues.append(
            Issue(
                code="FR-SIREN-INVALID",
                field=f"{side}.siren",
                message_fr=f"Le SIREN {label_fr} « {party.siren} » est invalide (9 chiffres, clé de contrôle).",
                message_en=f'The {label_en} SIREN "{party.siren}" is invalid (9 digits with a valid check digit).',
            )
        )
    elif not _blank(party.vat_id) and party.vat_id != _expected_vat_id(party.siren):
        expected = _expected_vat_id(party.siren)
        issues.append(
            Issue(
                code="FR-VAT-ID-MISMATCH",
                field=f"{side}.vat_id",
                message_fr=f"Le n° de TVA {label_fr} « {party.vat_id} » ne correspond pas au SIREN (attendu : {expected}).",
                message_en=f'The {label_en} VAT number "{party.vat_id}" does not match the SIREN (expected: {expected}).',
            )
        )
    if _blank(party.endpoint_id):
        issues.append(
            Issue(
                code="FR-ENDPOINT-MISSING",
                field=f"{side}.endpoint_id",
                message_fr=f"L’adresse électronique {label_fr} (plateforme agréée) est obligatoire.",
                message_en=f"The {label_en} electronic address (approved platform) is required.",
            )
        )
    return issues


def check_invoice(inv: Invoice) -> list[Issue]:
    """Return every problem found; an empty list means the invoice can be generated."""
    issues: list[Issue] = []

    if _blank(inv.number):
        issues.append(
            Issue(
                code="INV-NUMBER-MISSING",
                field="number",
                message_fr="Le numéro de facture est obligatoire.",
                message_en="The invoice number is required.",
            )
        )

    issues += _check_party(inv.seller, "seller", "du vendeur", "seller")
    issues += _check_party(inv.buyer, "buyer", "de l’acheteur", "buyer")

    if any(_blank(v) for v in (inv.buyer.street, inv.buyer.postcode, inv.buyer.city)):
        issues.append(
            Issue(
                code="FR-BUYER-ADDRESS-MISSING",
                field="buyer.address",
                message_fr="L’adresse complète de l’acheteur (rue, code postal, ville) est obligatoire.",
                message_en="The buyer's full address (street, postcode, city) is required.",
            )
        )

    delivery = inv.delivery_address
    if delivery is not None:
        if any(_blank(v) for v in (delivery.street, delivery.postcode, delivery.city)):
            issues.append(
                Issue(
                    code="FR-DELIVERY-ADDRESS-INCOMPLETE",
                    field="delivery_address",
                    message_fr="L’adresse de livraison est incomplète (rue, code postal et ville sont obligatoires). "
                    "Videz tous les champs si elle est identique à celle de l’acheteur.",
                    message_en="The delivery address is incomplete (street, postcode and city are required). "
                    "Clear all the fields if it is the same as the buyer's address.",
                )
            )
        if not re.fullmatch(r"[A-Z]{2}", delivery.country):
            issues.append(
                Issue(
                    code="FR-DELIVERY-COUNTRY-INVALID",
                    field="delivery_address.country",
                    message_fr=f"Pays de livraison « {delivery.country} » invalide (code à 2 lettres, par exemple FR).",
                    message_en=f'Delivery country "{delivery.country}" is invalid (2-letter code, for example FR).',
                )
            )

    given = {n.code for n in inv.notes if not _blank(n.text)}
    missing_notes = [c for c in REQUIRED_NOTE_CODES if c not in given]
    if missing_notes:
        issues.append(
            Issue(
                code="FR-LEGAL-NOTES-MISSING",
                field="notes",
                message_fr="Mentions légales manquantes : " + ", ".join(NOTE_LABELS[c][0] for c in missing_notes) + ".",
                message_en="Missing legal notes: " + ", ".join(NOTE_LABELS[c][1] for c in missing_notes) + ".",
            )
        )

    if not inv.lines:
        issues.append(
            Issue(
                code="INV-NO-LINES",
                field="lines",
                message_fr="La facture doit contenir au moins une ligne.",
                message_en="The invoice needs at least one line.",
            )
        )
    for n, line in enumerate(inv.lines, start=1):
        if line.quantity <= 0:
            issues.append(
                Issue(
                    code="INV-QTY-NOT-POSITIVE",
                    field=f"lines[{n}].quantity",
                    message_fr=f"Ligne {n} : la quantité doit être strictement positive (avoirs non gérés dans cette démo).",
                    message_en=f"Line {n}: the quantity must be greater than zero (credit notes are not supported in this demo).",
                )
            )
        if line.unit_price < 0:
            issues.append(
                Issue(
                    code="INV-PRICE-NEGATIVE",
                    field=f"lines[{n}].unit_price",
                    message_fr=f"Ligne {n} : le prix unitaire ne peut pas être négatif.",
                    message_en=f"Line {n}: the unit price cannot be negative.",
                )
            )
        if line.vat_rate not in SUPPORTED_VAT_RATES:
            rate = f"{line.vat_rate.normalize():f}"
            issues.append(
                Issue(
                    code="INV-VAT-RATE-UNKNOWN",
                    field=f"lines[{n}].vat_rate",
                    message_fr=f"Ligne {n} : taux de TVA {rate} % non géré (20, 10, 5,5 ou 2,1 %).",
                    message_en=f"Line {n}: VAT rate {rate} % is not supported (20, 10, 5.5 or 2.1 %).",
                )
            )

    if inv.due_date is not None and inv.due_date < inv.issue_date:
        issues.append(
            Issue(
                code="INV-DUE-BEFORE-ISSUE",
                field="due_date",
                message_fr="La date d’échéance ne peut pas précéder la date d’émission.",
                message_en="The due date cannot be earlier than the issue date.",
            )
        )

    return issues
