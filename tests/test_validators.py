import re

import pytest

from facturx_demo import validators
from facturx_demo.cii import build_cii_xml
from facturx_demo.samples import load_sample
from facturx_demo.validators import ValidatorUnavailable, run_kosit, run_mustang


def _martin_xml() -> bytes:
    return build_cii_xml(load_sample("martin"))


def _set_grand_total(xml: bytes, value: str) -> bytes:
    changed = re.sub(rb"(<ram:GrandTotalAmount[^>]*>)[^<]*", rb"\g<1>" + value.encode(), xml)
    assert changed != xml
    return changed


def _set_line_total(xml: bytes, value: str) -> bytes:
    """Change the first line's LineTotalAmount so the lines no longer add up."""
    changed = re.sub(rb"(<ram:LineTotalAmount[^>]*>)[^<]*", rb"\g<1>" + value.encode(), xml, count=1)
    assert changed != xml
    return changed


@pytest.mark.validators
def test_kosit_accepts_martin():
    report = run_kosit(_martin_xml())
    assert report.tool == "kosit"
    assert report.ok, report.findings
    assert [f for f in report.findings if f.severity == "error"] == []


@pytest.mark.validators
def test_kosit_rejects_wrong_grand_total():
    report = run_kosit(_set_grand_total(_martin_xml(), "361.00"))
    assert not report.ok
    assert "BR-CO-15" in {f.rule_id for f in report.findings}


@pytest.mark.validators
def test_kosit_rejects_wrong_line_total():
    report = run_kosit(_set_line_total(_martin_xml(), "250.00"))
    assert not report.ok
    assert "BR-CO-10" in {f.rule_id for f in report.findings}


@pytest.mark.validators
def test_kosit_reports_schema_errors():
    broken = _martin_xml().replace(b"<ram:ID>F-2027-0042</ram:ID>", b"<ram:IDX>F</ram:IDX>")
    report = run_kosit(broken)
    assert not report.ok
    assert any(f.rule_id == "XSD" for f in report.findings)


@pytest.mark.validators
def test_mustang_accepts_martin_xml():
    report = run_mustang(_martin_xml())
    assert report.tool == "mustang"
    assert report.ok, report.findings


@pytest.mark.validators
def test_mustang_rejects_wrong_grand_total():
    report = run_mustang(_set_grand_total(_martin_xml(), "361.00"))
    assert not report.ok
    assert "BR-CO-15" in {f.rule_id for f in report.findings}


def test_runners_raise_when_docker_missing(monkeypatch):
    monkeypatch.setattr(validators, "DOCKER", "docker-binary-that-does-not-exist")
    assert validators.docker_available() is False
    with pytest.raises(ValidatorUnavailable):
        run_kosit(b"<x/>")
    with pytest.raises(ValidatorUnavailable):
        run_mustang(b"<x/>")
