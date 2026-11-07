"""Run the reference validators (KoSIT, Mustang) in Docker and parse their reports.

Build the image once:  docker build -t facturx-validators:1 validators/
"""

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from lxml import etree
from pydantic import BaseModel

IMAGE = "facturx-validators:1"
DOCKER = "docker"  # module variable so tests can point it at a missing binary
TIMEOUT_SECONDS = 120

SVRL = "http://purl.oclc.org/dsdl/svrl"
KOSIT_REPORT_NS = "http://www.xoev.de/de/validator/framework/1/createreportinput"


class ValidatorUnavailable(Exception):
    """Docker is not running or the validator image is not built."""


class Finding(BaseModel):
    rule_id: str
    severity: Literal["error", "warning"]
    message: str
    location: str | None = None


class Report(BaseModel):
    tool: Literal["kosit", "mustang"]
    ok: bool
    findings: list[Finding]
    raw: str


def docker_available() -> bool:
    """True only if the Docker engine answers and the validator image exists."""
    try:
        done = subprocess.run(
            [DOCKER, "image", "inspect", IMAGE],
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _run_in_docker(work: Path, command: list[str]) -> subprocess.CompletedProcess:
    if not docker_available():
        raise ValidatorUnavailable(f"Docker or image {IMAGE} not available")
    try:
        return subprocess.run(
            [DOCKER, "run", "--rm", "-v", f"{work}:/work", IMAGE, *command],
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"validator timed out after {TIMEOUT_SECONDS}s") from exc


def run_kosit(xml: bytes) -> Report:
    """Validate CII XML with the KoSIT validator (Factur-X XSD + CEN EN 16931 rules)."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "invoice.xml").write_bytes(xml)
        done = _run_in_docker(
            work,
            [
                "java", "-jar", "/opt/kosit/validator.jar",
                "-s", "/opt/kosit/repo/scenarios.xml",
                "-r", "/opt/kosit/repo",
                "-o", "/work/out",
                "/work/invoice.xml",
            ],
        )  # fmt: skip
        report_file = work / "out" / "invoice-report.xml"
        if not report_file.exists():
            stderr = done.stderr.decode("utf-8", "replace")
            raise RuntimeError(f"KoSIT produced no report (exit {done.returncode}): {stderr}")
        raw = report_file.read_text(encoding="utf-8")
    findings = _parse_kosit(raw)
    ok = done.returncode == 0 and not any(f.severity == "error" for f in findings)
    return Report(tool="kosit", ok=ok, findings=findings, raw=raw)


def _parse_kosit(raw: str) -> list[Finding]:
    root = etree.fromstring(raw.encode("utf-8"))
    findings: list[Finding] = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        ns, _, local = el.tag[1:].partition("}")
        if ns == SVRL and local in ("failed-assert", "successful-report"):
            text = " ".join("".join(el.xpath("svrl:text//text()", namespaces={"svrl": SVRL})).split())
            severity = "warning" if el.get("flag") == "warning" else "error"
            findings.append(
                Finding(
                    rule_id=el.get("id") or "UNKNOWN",
                    severity=severity,
                    message=text,
                    location=el.get("location"),
                )
            )
        elif ns == KOSIT_REPORT_NS and local == "message":
            # XML Schema problems
            findings.append(
                Finding(rule_id="XSD", severity="error", message=(el.text or "").strip())
            )
    return findings


def run_mustang(data: bytes) -> Report:
    """Validate a Factur-X PDF (PDF/A-3 + XML) or a bare CII XML with Mustang."""
    is_pdf = data.startswith(b"%PDF")
    name = "invoice.pdf" if is_pdf else "invoice.xml"
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / name).write_bytes(data)
        done = _run_in_docker(
            work,
            [
                "java", "-jar", "/opt/mustang/Mustang-CLI.jar",
                "--action", "validate",
                "--no-notices",
                "--disable-file-logging",
                "--source", f"/work/{name}",
            ],
        )  # fmt: skip
    stdout = done.stdout.decode("utf-8", "replace")
    start = stdout.find("<?xml")
    end = stdout.rfind("</validation>")
    if start == -1 or end == -1:
        stderr = done.stderr.decode("utf-8", "replace")
        raise RuntimeError(f"Mustang produced no report (exit {done.returncode}): {stderr[-500:]}")
    raw = stdout[start : end + len("</validation>")]
    findings = _parse_mustang(raw)
    root = etree.fromstring(raw.encode("utf-8"))
    # Every section (pdf, xml, overall) must say "valid": Mustang's overall status can say
    # "valid" while its PDF/A section says "invalid".
    statuses = root.xpath("//summary/@status")
    ok = bool(statuses) and all(s == "valid" for s in statuses) and not any(
        f.severity == "error" for f in findings
    )
    return Report(tool="mustang", ok=ok, findings=findings, raw=raw)


def _mustang_rule_id(text: str, error_type: str) -> str:
    for pattern in (r"\[ID ([^\]]+)\]", r"^\s*\[([A-Za-z0-9_.-]+)\]", r"^\s*(BR-[A-Z0-9-]+)"):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return f"MUSTANG-{error_type}"


PDFA_FAILED = re.compile(
    r"TestAssertion \[ruleId=RuleId \[specification=(?P<spec>[^,]*), clause=(?P<clause>[^,]*), "
    r"testNumber=(?P<test>\d+)\], status=failed, message=(?P<message>.*?), location=Location"
)


def _parse_pdfa(text: str) -> list[Finding]:
    """The <pdf> section is a veraPDF dump as plain text: one Finding per failed rule."""
    counts: dict[tuple[str, str, str], int] = {}
    messages: dict[tuple[str, str, str], str] = {}
    for m in PDFA_FAILED.finditer(text):
        key = (m["spec"], m["clause"], m["test"])
        counts[key] = counts.get(key, 0) + 1
        messages.setdefault(key, m["message"])
    return [
        Finding(
            rule_id=f"PDFA-{clause}-{test}",
            severity="error",
            message=f"{spec}: {messages[(spec, clause, test)]} ({n}x)",
        )
        for (spec, clause, test), n in counts.items()
    ]


def _parse_mustang(raw: str) -> list[Finding]:
    root = etree.fromstring(raw.encode("utf-8"))
    findings: list[Finding] = []
    for pdf_el in root.xpath("/validation/pdf"):
        findings.extend(_parse_pdfa(pdf_el.text or ""))
    for el in root.xpath("//error | //warning"):
        text = " ".join("".join(el.itertext()).split())
        findings.append(
            Finding(
                rule_id=_mustang_rule_id(text, el.get("type", "?")),
                severity="error" if el.tag == "error" else "warning",
                message=text,
                location=el.get("location"),
            )
        )
    return findings
