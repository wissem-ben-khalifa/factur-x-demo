from decimal import Decimal

from stdnum.fr import siren

from facturx_demo.model import compute_totals
from facturx_demo.samples import load_sample


def test_martin_totals():
    totals = compute_totals(load_sample("martin"))
    assert totals.total_ht == Decimal("300.00")
    assert totals.total_vat == Decimal("60.00")
    assert totals.total_ttc == Decimal("360.00")
    assert len(totals.vat) == 1
    vat = totals.vat[0]
    assert (vat.rate, vat.basis, vat.amount) == (Decimal("20"), Decimal("300.00"), Decimal("60.00"))


def test_sample_sirens_are_fictional_and_valid():
    inv = load_sample("martin")
    for party in (inv.seller, inv.buyer):
        assert party.siren.startswith("000")
        assert siren.is_valid(party.siren)
