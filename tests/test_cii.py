import facturx
from lxml import etree

from facturx_demo.cii import build_cii_xml
from facturx_demo.samples import load_sample

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
}


def _root(xml: bytes):
    return etree.fromstring(xml)


def test_cii_passes_xsd():
    facturx.xml_check_xsd(build_cii_xml(load_sample("martin")), flavor="factur-x", level="en16931")


def test_cii_contains_key_fields():
    inv = load_sample("martin")
    root = _root(build_cii_xml(inv))
    assert root.xpath("//rsm:ExchangedDocument/ram:ID/text()", namespaces=NS) == ["F-2027-0042"]
    assert root.xpath("//ram:GrandTotalAmount/text()", namespaces=NS) == ["360.00"]
    assert root.xpath(
        "//ram:SellerTradeParty/ram:SpecifiedLegalOrganization/ram:ID[@schemeID='0002']/text()",
        namespaces=NS,
    ) == [inv.seller.siren]
    assert root.xpath(
        "//ram:BuyerTradeParty/ram:SpecifiedLegalOrganization/ram:ID[@schemeID='0002']/text()",
        namespaces=NS,
    ) == [inv.buyer.siren]
    assert root.xpath(
        "//ram:GuidelineSpecifiedDocumentContextParameter/ram:ID/text()", namespaces=NS
    ) == ["urn:cen.eu:en16931:2017"]


def test_cii_keeps_accents():
    xml = build_cii_xml(load_sample("martin")).decode("utf-8")
    assert "12 rue de l’Église" in xml
