"""One-page web app: fill an invoice, get a validated Factur-X PDF + XML.

Run:  uv run uvicorn facturx_demo.web.app:app --reload
"""

import logging
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from facturx_demo import validators
from facturx_demo.checks import Issue, check_invoice
from facturx_demo.pdf import generate
from facturx_demo.samples import load_sample
from facturx_demo.web.forms import LINE_COUNT, blank_form, invoice_to_form, parse_form

log = logging.getLogger("facturx_demo.web")

app = FastAPI(title="factur-x-demo", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

STORE = Path(tempfile.gettempdir()) / "facturx-demo"
KEEP_SECONDS = 3600
SAMPLES = ("martin", "multi_rate")
DOWNLOADS = {"factur-x.pdf": "application/pdf", "factur-x.xml": "application/xml"}


def _page(request: Request, name: str, status_code: int = 200, **context) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def _form_page(request: Request, form: dict[str, str], issues: list[Issue], status_code: int = 200):
    return _page(
        request, "index.html", status_code,
        form=form, issues=issues, lines=range(1, LINE_COUNT + 1), samples=SAMPLES,
    )  # fmt: skip


@app.get("/", response_class=HTMLResponse)
def index(request: Request, sample: str | None = None):
    # Only names from SAMPLES reach load_sample (no user-controlled file names).
    form = invoice_to_form(load_sample(sample)) if sample in SAMPLES else blank_form()
    return _form_page(request, form, [])


def _cleanup() -> None:
    if not STORE.exists():
        return
    cutoff = time.time() - KEEP_SECONDS
    for folder in STORE.iterdir():
        try:
            if folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


def _validate(pdf: bytes, xml: bytes) -> tuple[list, str | None]:
    """Run both validators. Returns (reports, None) or ([], reason) when unavailable."""
    if not validators.docker_available():
        return [], "docker"
    try:
        return [validators.run_kosit(xml), validators.run_mustang(pdf)], None
    except (validators.ValidatorUnavailable, RuntimeError) as exc:
        log.warning("validation failed: %s", exc)
        return [], "error"


def _process(request: Request, data: dict[str, str]):
    invoice, issues = parse_form(data)
    if invoice is not None and not issues:
        issues = check_invoice(invoice)
    if issues or invoice is None:
        return _form_page(request, data, issues, status_code=422)

    try:
        pdf, xml = generate(invoice)
    except Exception:  # a bug or a case the checks did not foresee: show a message, keep the log
        log.exception("generation failed")
        crash = Issue(
            code="GENERATION-FAILED", field="",
            message_fr="La génération a échoué. Vérifiez les valeurs saisies.",
            message_en="Generation failed. Please check the values you entered.",
        )  # fmt: skip
        return _form_page(request, data, [crash], status_code=500)

    _cleanup()
    invoice_id = str(uuid.uuid4())
    folder = STORE / invoice_id
    folder.mkdir(parents=True)
    (folder / "factur-x.pdf").write_bytes(pdf)
    (folder / "factur-x.xml").write_bytes(xml)

    reports, unavailable = _validate(pdf, xml)
    return _page(
        request, "result.html",
        invoice=invoice, invoice_id=invoice_id, reports=reports, unavailable=unavailable,
    )  # fmt: skip


@app.post("/generate", response_class=HTMLResponse)
async def generate_invoice(request: Request):
    form = await request.form()
    data = {key: value for key, value in form.items() if isinstance(value, str)}
    return await run_in_threadpool(_process, request, data)


@app.get("/download/{invoice_id}/{filename}")
def download(invoice_id: str, filename: str):
    if filename not in DOWNLOADS:
        return Response(status_code=404)
    try:
        parsed = uuid.UUID(invoice_id)
    except ValueError:
        return Response(status_code=404)
    if str(parsed) != invoice_id:  # only the canonical lowercase form is ever issued
        return Response(status_code=404)
    path = STORE / str(parsed) / filename
    if not path.is_file():
        return Response(status_code=404)
    return FileResponse(path, media_type=DOWNLOADS[filename], filename=filename)
