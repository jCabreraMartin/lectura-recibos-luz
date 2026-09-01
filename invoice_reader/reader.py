from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

import pdfplumber

from .ocr import ocr_pdf


NUMBER = r"(\d{1,3}(?:[. ]\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)"
DATE = r"(\d{1,2}/\d{1,2}/\d{4})"


def _decimal(value: str) -> Decimal:
    cleaned = value.replace(" ", "")
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Numero no reconocido: {value}") from exc


def _find_number(text: str, labels: Iterable[str], unit: str) -> Decimal | None:
    for label_pattern in labels:
        patterns = (
            rf"(?:{label_pattern})[^\n\d]{{0,60}}{NUMBER}\s*{unit}",
            rf"{NUMBER}\s*{unit}[^\n]{{0,60}}(?:{label_pattern})",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return _decimal(match.group(1))
    return None


def _find_period_consumption(text: str, period: str, alias: str) -> Decimal | None:
    # Give preference to the explicit consumption summary. Meter readings often
    # contain the same period names and much larger cumulative values.
    summary = re.search(
        r"consumos\s+desagregados[\s\S]{0,500}", text, flags=re.IGNORECASE
    )
    scope = summary.group(0) if summary else text
    return _find_number(scope, (period, alias), r"kWh")


def _as_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _normalized(text: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )


def _detect_supplier(text: str) -> str | None:
    folded = _normalized(text).lower()
    suppliers = {
        "iberdrola": "Iberdrola",
        "endesa": "Endesa",
        "totalenergies": "TotalEnergies",
        "naturgy": "Naturgy",
        "repsol": "Repsol",
        "octopus energy": "Octopus Energy",
    }
    for marker, name in suppliers.items():
        if marker in folded:
            return name
    return None


def _billing_period(text: str) -> dict[str, Any]:
    match = re.search(
        rf"{DATE}\s*(?:[-–]|a)\s*{DATE}", text, flags=re.IGNORECASE
    )
    if not match:
        return {"start": None, "end": None, "days": None}
    start = datetime.strptime(match.group(1), "%d/%m/%Y").date()
    end = datetime.strptime(match.group(2), "%d/%m/%Y").date()
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": (end - start).days,
    }


def _find_power(text: str, period: str) -> Decimal | None:
    labels = (
        rf"potencias?\s+contratadas?[^\n]{{0,40}}{period}",
        rf"pot\.?\s*{period}",
        rf"potencia\s+{period}",
    )
    return _find_number(text, labels, r"kW")


def _find_invoice_total(text: str) -> Decimal | None:
    for label in (
        r"total\s+importe\s+factura",
        r"total\s+importe\s+a\s+pagar",
        r"importe\s+total",
        r"total\s+a\s+pagar",
    ):
        match = re.search(rf"{label}[^\n\d]{{0,30}}{NUMBER}", text, re.IGNORECASE)
        if match:
            return _decimal(match.group(1))
    return None


def _find_amount(text: str, labels: Iterable[str]) -> Decimal | None:
    for label in labels:
        matches = re.finditer(rf"^.*{label}.*$", text, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            values = re.findall(rf"-?{NUMBER}", match.group(0))
            if values:
                return _decimal(values[-1])
    return None


def _find_services(text: str) -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not re.search(
            r"pack|mantenimiento|asistencia|proteccion|facilita|servicios?\s+endesa",
            line,
            re.I,
        ):
            continue
        values = re.findall(NUMBER, line)
        if not values:
            continue
        amount = _decimal(values[-1])
        name = re.split(r"\d", line, maxsplit=1)[0].strip(" .:-")
        if name:
            services.append({"name": name, "amount_eur": float(amount)})
    return services


def _extract_pdf_text(path: Path) -> list[str]:
    with pdfplumber.open(path) as document:
        return [(page.extract_text() or "") for page in document.pages]


def extract_pages(
    path: Path, use_ocr: bool = True, ocr_language: str | None = None
) -> tuple[list[str], bool]:
    pages = _extract_pdf_text(path)
    if any(page.strip() for page in pages):
        return pages, False
    if not use_ocr:
        raise ValueError("El PDF no contiene texto extraible y el OCR esta desactivado.")
    pages = ocr_pdf(path, language=ocr_language)
    if not any(page.strip() for page in pages):
        raise ValueError("El OCR no ha podido reconocer texto en el PDF.")
    return pages, True


def read_invoice(
    path: Path, use_ocr: bool = True, ocr_language: str | None = None
) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)

    pages, ocr_used = extract_pages(path, use_ocr=use_ocr, ocr_language=ocr_language)
    text = "\n".join(pages)

    total = _find_invoice_total(text)
    consumption_total = _find_number(
        text, (r"consumo\s+total", r"energia\s+consumida"), r"kWh"
    )
    periods = {
        "punta_kwh": _find_period_consumption(text, r"punta", r"P1"),
        "llano_kwh": _find_period_consumption(text, r"llano", r"P2"),
        "valle_kwh": _find_period_consumption(text, r"valle", r"P3"),
    }
    billing_period = _billing_period(text)
    power_punta = _find_power(text, r"punta")
    power_valle = _find_power(text, r"valle")

    warnings: list[str] = []
    if total is None:
        warnings.append("No se ha localizado el importe total.")
    if consumption_total is None:
        known = [value for value in periods.values() if value is not None]
        if len(known) == 3:
            consumption_total = sum(known, Decimal("0"))
        else:
            warnings.append("No se ha localizado el consumo total completo.")
    if billing_period["start"] is None:
        warnings.append("No se ha localizado el periodo de facturacion.")
    if power_punta is None and power_valle is None:
        warnings.append("No se ha localizado la potencia contratada.")

    return {
        "schema_version": "1.0",
        "source": {"filename": path.name, "pages": len(pages), "ocr_used": ocr_used},
        "supplier": _detect_supplier(text),
        "billing_period": billing_period,
        "consumption": {
            "total_kwh": _as_float(consumption_total),
            **{key: _as_float(value) for key, value in periods.items()},
        },
        "contracted_power": {
            "punta_kw": _as_float(power_punta),
            "valle_kw": _as_float(power_valle),
        },
        "amounts": {
            "energy_total_eur": _as_float(
                _find_amount(text, (r"(?:total\s+)?energ.?a",))
            ),
            "services_total_eur": _as_float(
                _find_amount(text, (r"total\s+servicios", r"importe\s+servicios"))
            ),
            "electricity_tax_eur": _as_float(
                _find_amount(text, (r"impuesto\s+(?:sobre\s+)?electricidad",))
            ),
            "meter_rental_eur": _as_float(_find_amount(text, (r"alquiler.*(?:equipo|contador)",))),
            "invoice_total_eur": _as_float(total),
        },
        "services": _find_services(text),
        "warnings": warnings,
    }

