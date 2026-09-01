from __future__ import annotations

import json
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from .batch import write_history
from .tariffs import load_offers, write_comparison
from .market import search_compare_and_write


PROJECT_DIR = Path(__file__).resolve().parent.parent


def _number(value: str, field: str, percentage: bool = False) -> float | None:
    cleaned = value.strip().replace(" ", "").replace(",", ".")
    if not cleaned:
        return None
    try:
        number = float(cleaned)
    except ValueError as exc:
        raise ValueError(f"{field}: introduce un numero valido.") from exc
    if number < 0:
        raise ValueError(f"{field}: el valor no puede ser negativo.")
    return number / 100 if percentage else number


def form_to_offer(values: dict[str, str]) -> dict[str, Any]:
    energy_type = values.get("energy_type", "fixed")
    energy: dict[str, Any] = {"type": energy_type}
    if energy_type == "fixed":
        energy["price_eur_kwh"] = _number(
            values.get("fixed_price", ""), "Precio fijo"
        )
    elif energy_type == "periods":
        for period, label in (("punta", "Punta"), ("llano", "Llano"), ("valle", "Valle")):
            energy[f"{period}_eur_kwh"] = _number(
                values.get(f"{period}_price", ""), f"Precio {label}"
            )
    else:
        raise ValueError("Selecciona precio fijo o por periodos.")

    return {
        "name": values.get("name", "").strip() or "Oferta sin nombre",
        "supplier": values.get("supplier", "").strip() or None,
        "energy": energy,
        "power": {
            "punta_eur_kw_day": _number(values.get("power_punta", ""), "Potencia punta"),
            "valle_eur_kw_day": _number(values.get("power_valle", ""), "Potencia valle"),
        },
        "services_monthly_eur": _number(values.get("services", ""), "Servicios"),
        "other_monthly_eur": _number(values.get("other", ""), "Otros costes"),
        "meter_rental_eur_day": _number(values.get("meter", ""), "Alquiler contador"),
        "electricity_tax_rate": _number(
            values.get("electricity_tax", ""), "Impuesto electrico", percentage=True
        ),
        "vat_rate": _number(values.get("vat", ""), "IVA", percentage=True),
    }


def offer_to_form(offer: dict[str, Any]) -> dict[str, str]:
    def rendered(value: Any, percentage: bool = False) -> str:
        if value is None:
            return ""
        number = float(value) * (100 if percentage else 1)
        return f"{number:g}".replace(".", ",")

    energy = offer.get("energy") or {}
    power = offer.get("power") or {}
    return {
        "name": str(offer.get("name") or ""),
        "supplier": str(offer.get("supplier") or ""),
        "energy_type": str(energy.get("type") or "fixed"),
        "fixed_price": rendered(energy.get("price_eur_kwh")),
        "punta_price": rendered(energy.get("punta_eur_kwh")),
        "llano_price": rendered(energy.get("llano_eur_kwh")),
        "valle_price": rendered(energy.get("valle_eur_kwh")),
        "power_punta": rendered(power.get("punta_eur_kw_day")),
        "power_valle": rendered(power.get("valle_eur_kw_day")),
        "services": rendered(offer.get("services_monthly_eur")),
        "other": rendered(offer.get("other_monthly_eur")),
        "meter": rendered(offer.get("meter_rental_eur_day")),
        "electricity_tax": rendered(offer.get("electricity_tax_rate"), True),
        "vat": rendered(offer.get("vat_rate"), True),
    }


class OptimizerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Optimizador de factura electrica")
        self.geometry("920x760")
        self.minsize(820, 680)
        self.configure(bg="#f4f7fb")
        self.folder = tk.StringVar(value=str(PROJECT_DIR / "facturas"))
        self.output = tk.StringVar(value=str(PROJECT_DIR / "salidas"))
        self.offers_path = tk.StringVar(value=str(PROJECT_DIR / "ofertas.private.json"))
        self.fields = {key: tk.StringVar() for key in offer_to_form({})}
        self.status = tk.StringVar(value="Preparado para procesar facturas.")
        self.report_paths: dict[str, Path] = {}
        self._build()
        self._load_offer(silent=True)

    def _build(self) -> None:
        style = ttk.Style(self)
        style.theme_use("vista" if "vista" in style.theme_names() else "clam")
        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"), foreground="#173b78")
        style.configure("Section.TLabelframe.Label", font=("Segoe UI", 11, "bold"))
        root = ttk.Frame(self, padding=22)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="Optimizador de factura electrica", style="Title.TLabel").pack(anchor="w")
        ttk.Label(root, text="Procesamiento local: las facturas y ofertas privadas no salen de este equipo.").pack(anchor="w", pady=(2, 16))

        locations = ttk.LabelFrame(root, text="Carpetas", style="Section.TLabelframe", padding=12)
        locations.pack(fill="x")
        self._path_row(locations, "Facturas", self.folder, self._choose_folder, 0)
        self._path_row(locations, "Salidas", self.output, self._choose_output, 1)
        self._path_row(locations, "Ofertas", self.offers_path, self._choose_offers, 2)

        offer = ttk.LabelFrame(root, text="Oferta electrica", style="Section.TLabelframe", padding=12)
        offer.pack(fill="both", expand=True, pady=14)
        labels = (
            ("name", "Nombre de la oferta"), ("supplier", "Comercializadora"),
            ("fixed_price", "Energia fija (EUR/kWh)"), ("punta_price", "Energia punta (EUR/kWh)"),
            ("llano_price", "Energia llano (EUR/kWh)"), ("valle_price", "Energia valle (EUR/kWh)"),
            ("power_punta", "Potencia punta (EUR/kW/dia)"), ("power_valle", "Potencia valle (EUR/kW/dia)"),
            ("services", "Servicios (EUR/mes)"), ("other", "Otros costes (EUR/mes)"),
            ("meter", "Contador (EUR/dia)"), ("electricity_tax", "Impuesto electrico (%)"),
            ("vat", "IVA (%)"),
        )
        ttk.Label(offer, text="Tipo de precio").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        energy_type = ttk.Combobox(offer, textvariable=self.fields["energy_type"], values=("fixed", "periods"), state="readonly", width=24)
        energy_type.grid(row=0, column=1, sticky="ew", padx=5, pady=5)
        energy_type.bind("<<ComboboxSelected>>", lambda _event: self._toggle_energy_fields())
        self.entries: dict[str, ttk.Entry] = {}
        for index, (key, label) in enumerate(labels, start=1):
            column = 0 if index <= 7 else 2
            row = index if index <= 7 else index - 7
            ttk.Label(offer, text=label).grid(row=row, column=column, sticky="w", padx=5, pady=5)
            entry = ttk.Entry(offer, textvariable=self.fields[key], width=25)
            entry.grid(row=row, column=column + 1, sticky="ew", padx=5, pady=5)
            self.entries[key] = entry
        offer.columnconfigure(1, weight=1)
        offer.columnconfigure(3, weight=1)

        actions = ttk.Frame(root)
        actions.pack(fill="x")
        ttk.Button(actions, text="Guardar oferta", command=self._save_offer).pack(side="left")
        ttk.Button(actions, text="Cargar oferta", command=self._load_offer).pack(side="left", padx=8)
        self.process_button = ttk.Button(actions, text="Procesar y comparar", command=self._start_processing)
        self.process_button.pack(side="right")
        self.search_button = ttk.Button(actions, text="Buscar ofertas actuales", command=self._start_search)
        self.search_button.pack(side="right", padx=8)
        ttk.Label(root, textvariable=self.status, wraplength=850).pack(fill="x", pady=(14, 8))
        reports = ttk.Frame(root)
        reports.pack(fill="x")
        ttk.Button(reports, text="Abrir informe historico", command=lambda: self._open_report("history")).pack(side="left")
        ttk.Button(reports, text="Abrir comparacion", command=lambda: self._open_report("comparison")).pack(side="left", padx=8)
        self._toggle_energy_fields()

    def _path_row(self, parent: ttk.LabelFrame, label: str, variable: tk.StringVar, command: Any, row: int) -> None:
        ttk.Label(parent, text=label, width=10).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=8, pady=4)
        ttk.Button(parent, text="Elegir...", command=command).grid(row=row, column=2, pady=4)
        parent.columnconfigure(1, weight=1)

    def _choose_folder(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.folder.get())
        if selected:
            self.folder.set(selected)

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output.get())
        if selected:
            self.output.set(selected)

    def _choose_offers(self) -> None:
        selected = filedialog.askopenfilename(filetypes=(("JSON", "*.json"), ("Todos", "*.*")))
        if selected:
            self.offers_path.set(selected)
            self._load_offer()

    def _toggle_energy_fields(self) -> None:
        fixed = self.fields["energy_type"].get() != "periods"
        if "fixed_price" not in self.entries:
            return
        self.entries["fixed_price"].configure(state="normal" if fixed else "disabled")
        for key in ("punta_price", "llano_price", "valle_price"):
            self.entries[key].configure(state="disabled" if fixed else "normal")

    def _values(self) -> dict[str, str]:
        return {key: value.get() for key, value in self.fields.items()}

    def _save_offer(self) -> bool:
        try:
            offer = form_to_offer(self._values())
            path = Path(self.offers_path.get())
            path.write_text(json.dumps({"offers": [offer]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.status.set(f"Oferta guardada de forma local en {path.name}.")
            return True
        except (OSError, ValueError) as exc:
            messagebox.showerror("No se pudo guardar", str(exc))
            return False

    def _load_offer(self, silent: bool = False) -> None:
        path = Path(self.offers_path.get())
        if not path.is_file():
            return
        try:
            values = offer_to_form(load_offers(path)[0])
            for key, value in values.items():
                self.fields[key].set(value)
            self._toggle_energy_fields()
            self.status.set(f"Oferta cargada desde {path.name}.")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            if not silent:
                messagebox.showerror("No se pudo cargar", str(exc))

    def _start_processing(self) -> None:
        if not self._save_offer():
            return
        self.process_button.configure(state="disabled")
        self.status.set("Procesando facturas y comparando la oferta...")
        threading.Thread(target=self._process, daemon=True).start()

    def _start_search(self) -> None:
        self.process_button.configure(state="disabled")
        self.search_button.configure(state="disabled")
        self.status.set("Consultando tarifas publicas oficiales y comparando localmente...")
        threading.Thread(target=self._search, daemon=True).start()

    def _search(self) -> None:
        try:
            output = Path(self.output.get())
            _json_path, history_html, history = write_history(Path(self.folder.get()), output)
            _offers, _comparison_json, comparison_html, comparison = search_compare_and_write(history, output)
            self.report_paths = {"history": history_html, "comparison": comparison_html}
            errors = comparison.get("search", {}).get("errors", [])
            result = f"Encontradas {len(comparison['offers'])} ofertas; fuentes con error: {len(errors)}. Informe preparado."
            self.after(0, lambda: self._finish(result))
        except Exception as exc:
            self.after(0, lambda: self._finish(f"Error en la busqueda: {exc}", error=True))

    def _process(self) -> None:
        try:
            output = Path(self.output.get())
            json_path, html_path, history = write_history(Path(self.folder.get()), output)
            comparison_json, comparison_html, comparison = write_comparison(
                history, Path(self.offers_path.get()), output
            )
            self.report_paths = {"history": html_path, "comparison": comparison_html}
            stats = history["processing"]
            offer = comparison["offers"][0]
            result = (
                f"Listo: {history['invoice_count']} facturas; nuevas {stats['new_count']}, "
                f"omitidas {stats['skipped_count']}, errores {stats['error_count']}. "
                f"Oferta {offer['status']}: coste estimado "
                f"{offer['estimated_total_eur'] if offer['estimated_total_eur'] is not None else 'pendiente'}."
            )
            self.after(0, lambda: self._finish(result))
        except Exception as exc:
            self.after(0, lambda: self._finish(f"Error: {exc}", error=True))

    def _finish(self, message: str, error: bool = False) -> None:
        self.process_button.configure(state="normal")
        self.search_button.configure(state="normal")
        self.status.set(message)
        if error:
            messagebox.showerror("No se pudo procesar", message)

    def _open_report(self, key: str) -> None:
        default = Path(self.output.get()) / ("informe_historico.html" if key == "history" else "comparacion_tarifas.html")
        path = self.report_paths.get(key, default)
        if not path.is_file():
            messagebox.showinfo("Informe no disponible", "Procesa las facturas antes de abrir el informe.")
            return
        os.startfile(path)


def main() -> None:
    OptimizerApp().mainloop()


if __name__ == "__main__":
    main()

