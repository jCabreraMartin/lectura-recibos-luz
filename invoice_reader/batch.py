from __future__ import annotations

import html
import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from .reader import read_invoice


def _sum(items: list[dict[str, Any]], *keys: str) -> float:
    total = 0.0
    for item in items:
        value: Any = item
        for key in keys:
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, (int, float)):
            total += float(value)
    return round(total, 2)


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def build_history(invoices: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        invoices,
        key=lambda invoice: invoice["billing_period"].get("start") or "9999-12-31",
    )
    days = sum(
        int(invoice["billing_period"].get("days") or 0) for invoice in ordered
    )
    total_kwh = _sum(ordered, "consumption", "total_kwh")
    invoice_total = _sum(ordered, "amounts", "invoice_total_eur")
    period_totals = {
        "punta_kwh": _sum(ordered, "consumption", "punta_kwh"),
        "llano_kwh": _sum(ordered, "consumption", "llano_kwh"),
        "valle_kwh": _sum(ordered, "consumption", "valle_kwh"),
    }
    services: dict[str, float] = defaultdict(float)
    for invoice in ordered:
        for service in invoice.get("services", []):
            services[service["name"]] += float(service.get("amount_eur") or 0)

    continuity_warnings: list[str] = []
    for previous, current in zip(ordered, ordered[1:]):
        previous_end = _date(previous["billing_period"].get("end"))
        current_start = _date(current["billing_period"].get("start"))
        if previous_end and current_start and previous_end != current_start:
            continuity_warnings.append(
                f"Discontinuidad entre {previous_end.isoformat()} y "
                f"{current_start.isoformat()}."
            )

    warnings = [
        warning
        for invoice in ordered
        for warning in invoice.get("warnings", [])
    ] + continuity_warnings
    return {
        "schema_version": "1.0",
        "invoice_count": len(ordered),
        "coverage": {
            "start": ordered[0]["billing_period"].get("start") if ordered else None,
            "end": ordered[-1]["billing_period"].get("end") if ordered else None,
            "days": days,
        },
        "totals": {
            "consumption_kwh": total_kwh,
            "invoice_eur": invoice_total,
            "punta_kwh": period_totals["punta_kwh"],
            "llano_kwh": period_totals["llano_kwh"],
            "valle_kwh": period_totals["valle_kwh"],
            "services_eur": _sum(ordered, "amounts", "services_total_eur"),
        },
        "indicators": {
            "annualized_consumption_kwh": round(total_kwh / days * 365, 0)
            if days
            else None,
            "average_invoice_eur": round(invoice_total / len(ordered), 2)
            if ordered
            else None,
            "all_in_cost_eur_kwh": round(invoice_total / total_kwh, 4)
            if total_kwh
            else None,
        },
        "services": [
            {"name": name, "amount_eur": round(amount, 2)}
            for name, amount in sorted(services.items())
        ],
        "warnings": warnings,
        "invoices": ordered,
    }


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def process_folder(
    folder: Path,
    use_ocr: bool = True,
    ocr_language: str | None = None,
    existing_history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not folder.is_dir():
        raise NotADirectoryError(folder)
    paths = sorted(folder.glob("*.pdf"))
    if not paths:
        raise ValueError(f"No se encontraron archivos PDF en {folder}")

    invoices = list((existing_history or {}).get("invoices", []))
    by_hash = {
        invoice.get("source", {}).get("sha256"): invoice
        for invoice in invoices
        if invoice.get("source", {}).get("sha256")
    }
    by_filename = {
        invoice.get("source", {}).get("filename"): invoice
        for invoice in invoices
        if invoice.get("source", {}).get("filename")
    }
    stats: dict[str, Any] = {
        "scanned_pdf_count": len(paths),
        "new_count": 0,
        "updated_count": 0,
        "indexed_count": 0,
        "skipped_count": 0,
        "duplicate_count": 0,
        "error_count": 0,
        "errors": [],
    }

    for path in paths:
        fingerprint = _fingerprint(path)
        if fingerprint in by_hash:
            stats["skipped_count"] += 1
            stats["duplicate_count"] += 1
            continue

        previous = by_filename.get(path.name)
        try:
            invoice = read_invoice(
                path, use_ocr=use_ocr, ocr_language=ocr_language
            )
        except Exception as exc:
            stats["error_count"] += 1
            stats["errors"].append({"filename": path.name, "message": str(exc)})
            continue

        invoice.setdefault("source", {})["sha256"] = fingerprint
        if previous:
            invoices.remove(previous)
            old_hash = previous.get("source", {}).get("sha256")
            if old_hash:
                by_hash.pop(old_hash, None)
                stats["updated_count"] += 1
            else:
                stats["indexed_count"] += 1
        else:
            stats["new_count"] += 1
        invoices.append(invoice)
        by_filename[path.name] = invoice
        by_hash[fingerprint] = invoice

    history = build_history(invoices)
    history["processing"] = stats
    return history


def _es(value: float | int | None, decimals: int = 2) -> str:
    if value is None:
        return "-"
    rendered = f"{value:,.{decimals}f}"
    return rendered.replace(",", "X").replace(".", ",").replace("X", ".")


def _period_label(invoice: dict[str, Any]) -> str:
    period = invoice["billing_period"]
    start = _date(period.get("start"))
    end = _date(period.get("end"))
    if not start or not end:
        return "Periodo desconocido"
    return f"{start.strftime('%d/%m/%Y')} - {end.strftime('%d/%m/%Y')}"


def render_html(history: dict[str, Any]) -> str:
    invoices = history["invoices"]
    totals = history["totals"]
    indicators = history["indicators"]
    max_consumption = max(
        (invoice["consumption"].get("total_kwh") or 0 for invoice in invoices),
        default=1,
    )
    rows = []
    chart_rows = []
    for invoice in invoices:
        consumption = invoice["consumption"]
        amounts = invoice["amounts"]
        label = _period_label(invoice)
        rows.append(
            "<tr>"
            f"<td>{html.escape(label)}</td>"
            f"<td>{html.escape(invoice.get('supplier') or '-')}</td>"
            f"<td class='num'>{_es(consumption.get('total_kwh'))}</td>"
            f"<td class='num'>{_es(consumption.get('punta_kwh'))}</td>"
            f"<td class='num'>{_es(consumption.get('llano_kwh'))}</td>"
            f"<td class='num'>{_es(consumption.get('valle_kwh'))}</td>"
            f"<td class='num'>{_es(amounts.get('invoice_total_eur'))} EUR</td>"
            "</tr>"
        )
        width = (consumption.get("total_kwh") or 0) / max_consumption * 100
        chart_rows.append(
            "<div class='bar-row'>"
            f"<span>{html.escape(label)}</span>"
            f"<div class='bar-track'><div class='bar' style='width:{width:.1f}%'></div></div>"
            f"<strong>{_es(consumption.get('total_kwh'))} kWh</strong>"
            "</div>"
        )

    distribution = []
    for label, key, color in (
        ("Punta", "punta_kwh", "#e85d75"),
        ("Llano", "llano_kwh", "#f2a93b"),
        ("Valle", "valle_kwh", "#3f8efc"),
    ):
        value = totals[key]
        share = value / totals["consumption_kwh"] * 100 if totals["consumption_kwh"] else 0
        distribution.append(
            f"<div class='period'><span style='background:{color}'></span>"
            f"<div><strong>{label}</strong><small>{_es(value)} kWh - {_es(share, 1)}%</small></div></div>"
        )

    services = "".join(
        f"<li><span>{html.escape(service['name'])}</span>"
        f"<strong>{_es(service['amount_eur'])} EUR</strong></li>"
        for service in history["services"]
    ) or "<li>No se han detectado servicios adicionales.</li>"
    warning_box = ""
    if history["warnings"]:
        warning_box = (
            "<section class='warnings'><h2>Advertencias</h2><ul>"
            + "".join(f"<li>{html.escape(item)}</li>" for item in history["warnings"])
            + "</ul></section>"
        )

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Informe historico de electricidad</title>
<style>
:root{{--ink:#152238;--muted:#66758a;--paper:#f4f7fb;--card:#fff;--line:#dfe7f1;--accent:#276ef1}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 Inter,Segoe UI,Arial,sans-serif}}
main{{max-width:1120px;margin:auto;padding:40px 24px 64px}} header{{padding:30px;border-radius:20px;background:linear-gradient(135deg,#173b78,#276ef1);color:white}}
h1{{margin:0 0 8px;font-size:32px}} header p{{margin:0;opacity:.86}} h2{{margin:0 0 18px;font-size:20px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:22px 0}} .card,section{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px}}
.card small{{display:block;color:var(--muted);margin-bottom:8px}} .card strong{{font-size:25px}} section{{margin-top:18px;overflow:auto}}
table{{width:100%;border-collapse:collapse;min-width:820px}} th,td{{padding:12px 10px;border-bottom:1px solid var(--line);text-align:left}} th{{font-size:12px;text-transform:uppercase;color:var(--muted)}}
.num{{text-align:right}} .bar-row{{display:grid;grid-template-columns:190px 1fr 100px;gap:12px;align-items:center;margin:12px 0}} .bar-track{{height:12px;background:#edf2f8;border-radius:10px;overflow:hidden}} .bar{{height:100%;background:linear-gradient(90deg,#70a6ff,#276ef1);border-radius:10px}}
.periods{{display:flex;gap:28px;flex-wrap:wrap}} .period{{display:flex;align-items:center;gap:10px}} .period>span{{width:12px;height:36px;border-radius:8px}} .period small{{display:block;color:var(--muted)}}
.services{{list-style:none;padding:0;margin:0}} .services li{{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--line)}} .warnings{{border-color:#f1c46b;background:#fffaf0}}
footer{{color:var(--muted);text-align:center;margin-top:24px;font-size:13px}}
@media(max-width:760px){{.cards{{grid-template-columns:1fr 1fr}}.bar-row{{grid-template-columns:1fr}}}}
@media print{{body{{background:white}}main{{max-width:none;padding:0}}section,.card,header{{break-inside:avoid}}}}
</style></head><body><main>
<header><h1>Informe historico de electricidad</h1><p>{history['invoice_count']} facturas - {_es(history['coverage']['days'], 0)} dias analizados - {history['coverage']['start']} a {history['coverage']['end']}</p></header>
<div class="cards">
<div class="card"><small>Consumo acumulado</small><strong>{_es(totals['consumption_kwh'])} kWh</strong></div>
<div class="card"><small>Importe acumulado</small><strong>{_es(totals['invoice_eur'])} EUR</strong></div>
<div class="card"><small>Proyeccion anual</small><strong>{_es(indicators['annualized_consumption_kwh'],0)} kWh</strong></div>
<div class="card"><small>Coste total / consumo</small><strong>{_es(indicators['all_in_cost_eur_kwh'],4)} EUR/kWh</strong></div>
</div>
<section><h2>Evolucion del consumo</h2>{''.join(chart_rows)}</section>
<section><h2>Distribucion horaria</h2><div class="periods">{''.join(distribution)}</div></section>
<section><h2>Detalle por factura</h2><table><thead><tr><th>Periodo</th><th>Compania</th><th class="num">Total kWh</th><th class="num">Punta</th><th class="num">Llano</th><th class="num">Valle</th><th class="num">Factura</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>
<section><h2>Servicios detectados</h2><ul class="services">{services}</ul></section>
{warning_box}<footer>Informe generado localmente. Las cifras son historicas y no constituyen una oferta comercial.</footer>
</main></body></html>"""


def write_history(
    folder: Path,
    output_dir: Path,
    use_ocr: bool = True,
    ocr_language: str | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "historico_facturas.json"
    html_path = output_dir / "informe_historico.html"
    existing_history = None
    if json_path.is_file():
        try:
            existing_history = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing_history = None
    history = process_folder(
        folder,
        use_ocr=use_ocr,
        ocr_language=ocr_language,
        existing_history=existing_history,
    )
    json_path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    html_path.write_text(render_html(history), encoding="utf-8")
    return json_path, html_path, history

