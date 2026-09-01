from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


REQUIRED_COST_FIELDS = (
    "power.punta_eur_kw_day",
    "power.valle_eur_kw_day",
    "services_monthly_eur",
    "other_monthly_eur",
    "meter_rental_eur_day",
    "electricity_tax_rate",
    "vat_rate",
)


def _nested(data: dict[str, Any], dotted_key: str) -> Any:
    value: Any = data
    for key in dotted_key.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _energy_cost(invoice: dict[str, Any], offer: dict[str, Any]) -> tuple[float | None, list[str]]:
    energy = offer.get("energy") or {}
    consumption = invoice.get("consumption") or {}
    kind = energy.get("type")
    if kind == "fixed":
        price = energy.get("price_eur_kwh")
        total = consumption.get("total_kwh")
        if price is None or total is None:
            return None, ["Falta el precio fijo o el consumo total."]
        return float(price) * float(total), []
    if kind == "periods":
        total = 0.0
        missing = []
        for period in ("punta", "llano", "valle"):
            price = energy.get(f"{period}_eur_kwh")
            consumed = consumption.get(f"{period}_kwh")
            if price is None or consumed is None:
                missing.append(period)
            else:
                total += float(price) * float(consumed)
        if missing:
            return None, ["Faltan precios o consumos por periodo: " + ", ".join(missing) + "."]
        return total, []
    return None, ["El tipo de energia debe ser 'fixed' o 'periods'."]


def compare_offer(history: dict[str, Any], offer: dict[str, Any]) -> dict[str, Any]:
    missing_fields = [key for key in REQUIRED_COST_FIELDS if _nested(offer, key) is None]
    breakdown = {
        "energy_eur": 0.0,
        "power_eur": 0.0,
        "services_eur": 0.0,
        "other_eur": 0.0,
        "meter_rental_eur": 0.0,
        "electricity_tax_eur": 0.0,
        "vat_eur": 0.0,
    }
    warnings: list[str] = []
    complete = not missing_fields

    for invoice in history.get("invoices", []):
        days = invoice.get("billing_period", {}).get("days")
        energy_cost, energy_warnings = _energy_cost(invoice, offer)
        if energy_cost is None:
            complete = False
        else:
            breakdown["energy_eur"] += energy_cost
        warnings.extend(energy_warnings)

        if days is None:
            complete = False
            warnings.append("Una factura no contiene el numero de dias.")
            continue
        days = float(days)
        powers = invoice.get("contracted_power") or {}
        power_offer = offer.get("power") or {}
        for period in ("punta", "valle"):
            price = power_offer.get(f"{period}_eur_kw_day")
            contracted = powers.get(f"{period}_kw")
            if price is not None and contracted is not None:
                breakdown["power_eur"] += float(price) * float(contracted) * days
            elif price is not None:
                complete = False
                warnings.append(f"Falta la potencia contratada {period} en una factura.")
        if offer.get("services_monthly_eur") is not None:
            breakdown["services_eur"] += float(offer["services_monthly_eur"]) * days * 12 / 365
        if offer.get("other_monthly_eur") is not None:
            breakdown["other_eur"] += float(offer["other_monthly_eur"]) * days * 12 / 365
        if offer.get("meter_rental_eur_day") is not None:
            breakdown["meter_rental_eur"] += float(offer["meter_rental_eur_day"]) * days

    taxable = sum(
        breakdown[key]
        for key in ("energy_eur", "power_eur", "services_eur", "other_eur")
    )
    if offer.get("electricity_tax_rate") is not None:
        breakdown["electricity_tax_eur"] = taxable * float(offer["electricity_tax_rate"])
    subtotal = taxable + breakdown["meter_rental_eur"] + breakdown["electricity_tax_eur"]
    if offer.get("vat_rate") is not None:
        breakdown["vat_eur"] = subtotal * float(offer["vat_rate"])

    breakdown = {key: round(value, 2) for key, value in breakdown.items()}
    known_total = round(sum(breakdown.values()), 2)
    actual_total = history.get("totals", {}).get("invoice_eur")
    estimated_total = known_total if complete else None
    savings = round(float(actual_total) - estimated_total, 2) if estimated_total is not None and actual_total is not None else None
    if missing_fields:
        warnings.insert(0, "Faltan datos de la oferta: " + ", ".join(missing_fields) + ".")

    return {
        "name": offer.get("name") or "Oferta sin nombre",
        "supplier": offer.get("supplier"),
        "status": "complete" if complete else "incomplete",
        "missing_fields": missing_fields,
        "breakdown": breakdown,
        "known_partial_total_eur": known_total,
        "estimated_total_eur": estimated_total,
        "historical_actual_total_eur": actual_total,
        "historical_savings_eur": savings,
        "warnings": list(dict.fromkeys(warnings)),
    }


def compare_offers(history: dict[str, Any], offers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "invoice_count": history.get("invoice_count", 0),
        "coverage": history.get("coverage"),
        "historical_actual_total_eur": history.get("totals", {}).get("invoice_eur"),
        "offers": [compare_offer(history, offer) for offer in offers],
    }


def _eur(value: float | None) -> str:
    if value is None:
        return "Pendiente"
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " EUR"


def render_comparison_html(comparison: dict[str, Any]) -> str:
    cards = []
    for offer in comparison["offers"]:
        complete = offer["status"] == "complete"
        result = _eur(offer["estimated_total_eur"])
        savings = _eur(offer["historical_savings_eur"])
        warnings = "".join(f"<li>{html.escape(item)}</li>" for item in offer["warnings"])
        cards.append(
            "<article>"
            f"<span class='status {'ok' if complete else 'pending'}'>{'Completa' if complete else 'Incompleta'}</span>"
            f"<h2>{html.escape(offer['name'])}</h2>"
            f"<p>{html.escape(offer.get('supplier') or 'Comercializadora sin indicar')}</p>"
            f"<div class='metric'><small>Coste estimado</small><strong>{result}</strong></div>"
            f"<div class='metric'><small>Ahorro historico</small><strong>{savings}</strong></div>"
            f"<div class='metric'><small>Coste parcial conocido</small><strong>{_eur(offer['known_partial_total_eur'])}</strong></div>"
            f"<ul>{warnings}</ul>"
            "</article>"
        )
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Comparacion de tarifas electricas</title><style>
body{{margin:0;background:#f4f7fb;color:#152238;font:15px/1.5 Segoe UI,Arial,sans-serif}}main{{max-width:1050px;margin:auto;padding:40px 24px}}
header{{background:linear-gradient(135deg,#173b78,#276ef1);color:white;padding:28px;border-radius:18px}}h1{{margin:0 0 8px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;margin-top:20px}}
article{{background:white;border:1px solid #dfe7f1;border-radius:16px;padding:22px}}article h2{{margin:12px 0 0}}article p{{color:#66758a;margin-top:2px}}.status{{display:inline-block;padding:4px 9px;border-radius:20px;font-size:12px}}.ok{{background:#dff6e8;color:#17633a}}.pending{{background:#fff0cf;color:#805500}}
.metric{{border-top:1px solid #e6edf5;padding:12px 0}}.metric small{{display:block;color:#66758a}}.metric strong{{font-size:20px}}ul{{padding-left:20px;color:#805500}}
</style></head><body><main><header><h1>Comparacion de tarifas</h1><p>{comparison['invoice_count']} facturas historicas. Coste real: {_eur(comparison['historical_actual_total_eur'])}</p></header><div class="grid">{''.join(cards)}</div></main></body></html>"""


def load_offers(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    offers = data.get("offers") if isinstance(data, dict) else data
    if not isinstance(offers, list) or not offers:
        raise ValueError("El archivo de ofertas debe contener una lista no vacia.")
    return offers


def write_comparison(history: dict[str, Any], offers_path: Path, output_dir: Path) -> tuple[Path, Path, dict[str, Any]]:
    comparison = compare_offers(history, load_offers(offers_path))
    json_path = output_dir / "comparacion_tarifas.json"
    html_path = output_dir / "comparacion_tarifas.html"
    json_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(render_comparison_html(comparison), encoding="utf-8")
    return json_path, html_path, comparison

