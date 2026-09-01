from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from .tariffs import compare_offers, render_comparison_html


ENDESA_URL = "https://www.endesa.com/es/luz-y-gas/luz/conecta-de-endesa"
NATURGY_URL = "https://www.naturgy.es/hogar/luz"
TOTALENERGIES_URL = "https://www.totalenergies.es/es/hogares/atencion-al-cliente/que-necesitas/precios-en-vigor-luz"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.parts)).strip()


def _download_text(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "lectura-recibos-luz/0.1 (+comparador local)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        content = response.read().decode(charset, errors="replace")
    parser = _TextExtractor()
    parser.feed(content)
    return parser.text()


def _value(text: str, pattern: str) -> float:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        raise ValueError(f"No se ha encontrado el precio esperado: {pattern}")
    return float(match.group(1).replace(".", "").replace(",", "."))


def _base_offer(name: str, supplier: str, source_url: str, energy: dict[str, Any], power_punta: float, power_valle: float) -> dict[str, Any]:
    return {
        "name": name,
        "supplier": supplier,
        "energy": energy,
        "power": {
            "punta_eur_kw_day": power_punta,
            "valle_eur_kw_day": power_valle,
        },
        "services_monthly_eur": 0.0,
        "other_monthly_eur": 0.024688 * 365 / 12,
        "meter_rental_eur_day": None,
        "electricity_tax_rate": 0.0511269632,
        "vat_rate": 0.21,
        "source_url": source_url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "confidence": "medium",
        "assumptions": [
            "Precios de energia y potencia sin impuestos.",
            "IVA peninsular del 21% e impuesto electrico del 5,11269632%.",
            "Financiacion del bono social aproximada a 0,024688 EUR/dia.",
            "Sin servicios opcionales contratados.",
        ],
    }


def parse_endesa(text: str) -> list[dict[str, Any]]:
    energy = _value(text, r"T\.\s*de energ(?:i|í)a.*?(\d+[,.]\d+)\s*€/kWh")
    valley_month = _value(text, r"potencia hora valle.*?(\d+[,.]\d+)\s*€/kW")
    punta_month = _value(text, r"potencia hora punta-llano.*?(\d+[,.]\d+)\s*€/kW")
    offer = _base_offer(
        "Tarifa Conecta Luz",
        "Endesa",
        ENDESA_URL,
        {"type": "fixed", "price_eur_kwh": energy},
        punta_month * 12 / 365,
        valley_month * 12 / 365,
    )
    offer["conditions"] = "Nueva contratacion, contratacion online y sin permanencia. Precio promocional publicado."
    return [offer]


def parse_naturgy(text: str) -> list[dict[str, Any]]:
    fixed = _value(text, r"Tarifa Por Uso Luz.*?(\d+[,.]\d+)\s*€/kWh")
    power_section = re.search(r"Precios t(?:e|é)rmino potencia(.*?)(?:Permanencia|Contratar)", text, re.I)
    if not power_section:
        raise ValueError("No se ha encontrado la tabla de potencia de Naturgy.")
    power_values = [
        float(value.replace(".", "").replace(",", "."))
        for value in re.findall(r"(\d+[,.]\d+)\s*€/kW\*d(?:i|í)a", power_section.group(1), re.I)
    ]
    if len(power_values) < 3:
        raise ValueError("La tabla de potencia de Naturgy esta incompleta.")
    # La tabla intercala la columna sin impuestos y la columna con impuestos:
    # P1 sin, P1 con, P2 sin, P2 con.
    p1, p2 = power_values[0], power_values[2]
    usage = _base_offer(
        "Tarifa Por Uso Luz", "Naturgy", NATURGY_URL,
        {"type": "fixed", "price_eur_kwh": fixed}, p1, p2,
    )
    usage["conditions"] = "Precio estable 12 meses, sin permanencia y sin servicios obligatorios."
    valley = _value(text, r"Valle:\s*(\d+[,.]\d+)\s*€/kWh")
    llano = _value(text, r"Llano:\s*(\d+[,.]\d+)\s*€/kWh")
    punta = _value(text, r"Punta:\s*(\d+[,.]\d+)\s*€/kWh")
    night = _base_offer(
        "Tarifa Noche Luz", "Naturgy", NATURGY_URL,
        {"type": "periods", "punta_eur_kwh": punta, "llano_eur_kwh": llano, "valle_eur_kwh": valley}, p1, p2,
    )
    night["conditions"] = "Tres periodos, sin permanencia y sin servicios obligatorios."
    return [usage, night]


def parse_totalenergies(text: str) -> list[dict[str, Any]]:
    section_fixed = re.search(r"Precios Luz A tu Aire Siempre sin impuestos(.*?)Precios Luz A tu Aire Siempre con impuestos", text, re.I)
    section_periods = re.search(r"Precios Luz A tu Aire Ahorro sin impuestos(.*?)Precios Luz A tu Aire Ahorro con impuestos", text, re.I)
    if not section_fixed or not section_periods:
        raise ValueError("No se han encontrado las tablas de precios sin impuestos.")
    fixed_values = [float(value.replace(",", ".")) for value in re.findall(r"0[,.]\d+", section_fixed.group(1))]
    period_values = [float(value.replace(",", ".")) for value in re.findall(r"0[,.]\d+", section_periods.group(1))]
    if len(fixed_values) < 3 or len(period_values) < 5:
        raise ValueError("Las tablas de TotalEnergies no contienen todos los precios.")
    fixed = _base_offer(
        "A Tu Aire Luz Siempre", "TotalEnergies", TOTALENERGIES_URL,
        {"type": "fixed", "price_eur_kwh": fixed_values[2]}, fixed_values[0], fixed_values[1],
    )
    fixed["conditions"] = "Precio fijo anual, sin descuentos ni mantenimiento opcional."
    periods = _base_offer(
        "A Tu Aire Programa Tu Ahorro", "TotalEnergies", TOTALENERGIES_URL,
        {"type": "periods", "punta_eur_kwh": period_values[2], "llano_eur_kwh": period_values[3], "valle_eur_kwh": period_values[4]},
        period_values[0], period_values[1],
    )
    periods["conditions"] = "Tres periodos, precios anuales sin descuentos ni mantenimiento opcional."
    return [fixed, periods]


PROVIDERS: tuple[tuple[str, str, Callable[[str], list[dict[str, Any]]]], ...] = (
    ("Endesa", ENDESA_URL, parse_endesa),
    ("Naturgy", NATURGY_URL, parse_naturgy),
    ("TotalEnergies", TOTALENERGIES_URL, parse_totalenergies),
)


def _historical_meter_rate(history: dict[str, Any]) -> float | None:
    amount = 0.0
    days = 0
    for invoice in history.get("invoices", []):
        rental = invoice.get("amounts", {}).get("meter_rental_eur")
        invoice_days = invoice.get("billing_period", {}).get("days")
        if rental is not None and invoice_days:
            amount += float(rental)
            days += int(invoice_days)
    return amount / days if days else None


def search_public_offers(history: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    offers: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    meter_rate = _historical_meter_rate(history)
    for supplier, url, parser in PROVIDERS:
        try:
            found = parser(_download_text(url, timeout=timeout))
            for offer in found:
                offer["meter_rental_eur_day"] = meter_rate
                offer.setdefault("assumptions", []).append(
                    "Alquiler de contador estimado con la media diaria del historico."
                )
            offers.extend(found)
        except Exception as exc:
            errors.append({"supplier": supplier, "source_url": url, "message": str(exc)})
    if not offers:
        raise RuntimeError("No se ha podido obtener ninguna oferta publica.")
    return {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "offers": offers,
        "errors": errors,
    }


def search_compare_and_write(history: dict[str, Any], output_dir: Path) -> tuple[Path, Path, Path, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    catalog = search_public_offers(history)
    comparison = compare_offers(history, catalog["offers"])
    comparison["search"] = {"retrieved_at": catalog["retrieved_at"], "errors": catalog["errors"]}
    offers_path = output_dir / "ofertas_encontradas.json"
    json_path = output_dir / "comparacion_tarifas.json"
    html_path = output_dir / "comparacion_tarifas.html"
    offers_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(render_comparison_html(comparison), encoding="utf-8")
    return offers_path, json_path, html_path, comparison

