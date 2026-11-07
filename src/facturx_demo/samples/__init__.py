"""Fictional sample invoices (JSON files in this folder)."""

from pathlib import Path

from facturx_demo.model import Invoice

_DIR = Path(__file__).parent


def load_sample(name: str) -> Invoice:
    return Invoice.model_validate_json((_DIR / f"{name}.json").read_text(encoding="utf-8"))
