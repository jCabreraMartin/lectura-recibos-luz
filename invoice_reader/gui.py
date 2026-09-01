from __future__ import annotations

import json
import os
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from .batch import write_history
from .tariffs import load_offers, write_comparison
from .market import search_compare_and_write


PROJECT_DIR = Path(__file__).resolve().parent.parent
SETTINGS_FILENAME = "configuracion.json"


def default_data_dir() -> Path:
    configured = os.environ.get("LECTURA_RECIBOS_DATA_DIR")
    if configured:
        return Path(configured)
    if not getattr(sys, "frozen", False) and (PROJECT_DIR / "facturas").is_dir():
        return PROJECT_DIR
    return Path.home() / "Documents" / "OptimizadorFacturaElectrica"


def suggested_paths(data_dir: Path) -> dict[str, Path]:
    legacy = Path.home() / "Documents" / "ChatGPT" / "OptimizadorFacturaElectrica"
    base = legacy if any((legacy / "facturas").glob("*.pdf")) else data_dir
    offers = base / "ofertas.private.json"
    if not offers.is_file():
        offers = data_dir / "ofertas.private.json"
    return {
        "facturas": base / "facturas",
        "salidas": base / "salidas",
        "ofertas": offers,
    }


def load_settings(data_dir: Path) -> dict[str, Path] | None:
    path = data_dir / SETTINGS_FILENAME
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {key: Path(raw[key]) for key in ("facturas", "salidas", "ofertas")}
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None


def save_settings(data_dir: Path, paths: dict[str, Path]) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / SETTINGS_FILENAME
    path.write_text(
        json.dumps({key: str(value) for key, value in paths.items()}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


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
        self.data_dir = default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        paths = load_settings(self.data_dir) or suggested_paths(self.data_dir)
        paths["facturas"].mkdir(parents=True, exist_ok=True)
        paths["salidas"].mkdir(parents=True, exist_ok=True)
        self.folder = tk.StringVar(value=str(paths["facturas"]))
        self.output = tk.StringVar(value=str(paths["salidas"]))
        self.offers_path = tk.StringVar(value=str(paths["ofertas"]))
        self.fields = {key: tk.StringVar() for key in offer_to_form({})}
        self.status = tk.StringVar(value="Preparado para procesar facturas.")
        self.progress_text = tk.StringVar(value="")
        self.progress_value = tk.DoubleVar(value=0)
        self.worker_events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._polling_events = False
        self.report_paths: dict[str, Path] = {}
        self._build()
        self._load_offer(silent=True)
        if load_settings(self.data_dir) is None:
            self.after(150, self._show_first_run)

    def _build(self) -> None:
        style = ttk.Style(self)
        style.theme_use("vista" if "vista" in style.theme_names() else "clam")
        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"), foreground="#173b78")
        style.configure("Subtitle.TLabel", font=("Segoe UI", 11), foreground="#50627a")
        style.configure("Section.TLabelframe.Label", font=("Segoe UI", 11, "bold"))
        style.configure("Action.TButton", font=("Segoe UI", 11, "bold"), padding=(14, 10))
        root = ttk.Frame(self, padding=22)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="Optimizador de factura electrica", style="Title.TLabel").pack(anchor="w")
        ttk.Label(root, text="Tus facturas y consumos se procesan siempre en este equipo.", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 14))

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)
        home = ttk.Frame(notebook, padding=18)
        manual = ttk.Frame(notebook, padding=18)
        settings = ttk.Frame(notebook, padding=18)
        notebook.add(home, text="Inicio")
        notebook.add(manual, text="Oferta manual")
        notebook.add(settings, text="Configuracion")

        ttk.Label(home, text="¿Que quieres hacer?", font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 12))
        history_card = ttk.LabelFrame(home, text="1. Actualizar el historico", style="Section.TLabelframe", padding=16)
        history_card.pack(fill="x", pady=6)
        ttk.Label(history_card, text="Lee solo las facturas nuevas o modificadas y actualiza el informe de consumo.", wraplength=620).pack(side="left", fill="x", expand=True)
        self.history_button = ttk.Button(history_card, text="Actualizar facturas", style="Action.TButton", command=self._start_history)
        self.history_button.pack(side="right", padx=(16, 0))

        search_card = ttk.LabelFrame(home, text="2. Buscar una tarifa mejor", style="Section.TLabelframe", padding=16)
        search_card.pack(fill="x", pady=6)
        ttk.Label(search_card, text="Consulta ofertas publicas actuales y calcula cuanto habrias pagado con tu consumo real.", wraplength=620).pack(side="left", fill="x", expand=True)
        self.search_button = ttk.Button(search_card, text="Buscar ofertas", style="Action.TButton", command=self._start_search)
        self.search_button.pack(side="right", padx=(16, 0))

        reports = ttk.LabelFrame(home, text="3. Ver resultados", style="Section.TLabelframe", padding=16)
        reports.pack(fill="x", pady=6)
        ttk.Button(reports, text="Abrir informe historico", command=lambda: self._open_report("history")).pack(side="left")
        ttk.Button(reports, text="Abrir comparacion de tarifas", command=lambda: self._open_report("comparison")).pack(side="left", padx=10)
        ttk.Label(home, text="Usa 'Oferta manual' solamente para comparar una propuesta recibida por telefono, correo o documento.", foreground="#66758a", wraplength=760).pack(anchor="w", pady=(16, 0))

        offer = ttk.LabelFrame(manual, text="Datos de la oferta", style="Section.TLabelframe", padding=12)
        offer.pack(fill="both", expand=True)
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

        actions = ttk.Frame(manual)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="Guardar oferta", command=self._save_offer).pack(side="left")
        ttk.Button(actions, text="Cargar oferta", command=self._load_offer).pack(side="left", padx=8)
        self.process_button = ttk.Button(actions, text="Comparar esta oferta", style="Action.TButton", command=self._start_processing)
        self.process_button.pack(side="right")

        locations = ttk.LabelFrame(settings, text="Ubicaciones", style="Section.TLabelframe", padding=16)
        locations.pack(fill="x")
        self._path_row(locations, "Facturas", self.folder, self._choose_folder, 0)
        self._path_row(locations, "Salidas", self.output, self._choose_output, 1)
        self._path_row(locations, "Ofertas", self.offers_path, self._choose_offers, 2)
        ttk.Button(settings, text="Guardar configuracion", command=self._save_settings).pack(anchor="e", pady=(12, 0))
        ttk.Label(settings, text="Normalmente no necesitas cambiar estas rutas. Las carpetas privadas estan excluidas del repositorio.", foreground="#66758a", wraplength=760).pack(anchor="w", pady=14)

        ttk.Label(root, textvariable=self.status, wraplength=850).pack(fill="x", pady=(14, 4))
        ttk.Progressbar(root, variable=self.progress_value, maximum=100).pack(fill="x", pady=2)
        ttk.Label(root, textvariable=self.progress_text, foreground="#50627a").pack(fill="x")
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

    def _current_paths(self) -> dict[str, Path]:
        return {
            "facturas": Path(self.folder.get()),
            "salidas": Path(self.output.get()),
            "ofertas": Path(self.offers_path.get()),
        }

    def _save_settings(self, notify: bool = True) -> bool:
        try:
            paths = self._current_paths()
            paths["facturas"].mkdir(parents=True, exist_ok=True)
            paths["salidas"].mkdir(parents=True, exist_ok=True)
            save_settings(self.data_dir, paths)
            if notify:
                self.status.set("Configuracion guardada. Estas rutas se conservaran al volver a abrir.")
            return True
        except OSError as exc:
            messagebox.showerror("No se pudo guardar la configuracion", str(exc))
            return False

    def _show_first_run(self) -> None:
        wizard = tk.Toplevel(self)
        wizard.title("Primer inicio")
        wizard.transient(self)
        wizard.grab_set()
        wizard.resizable(False, False)
        body = ttk.Frame(wizard, padding=22)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Prepara tus carpetas", font=("Segoe UI", 17, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )
        count = len(list(Path(self.folder.get()).glob("*.pdf")))
        detail = (
            f"Hemos encontrado {count} facturas en una ubicacion anterior. Confirma las rutas para conservar tu historico."
            if count
            else "Elige donde guardar tus facturas y resultados. Puedes cambiarlo mas adelante en Configuracion."
        )
        ttk.Label(body, text=detail, wraplength=610).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 16)
        )
        self._wizard_path_row(body, "Facturas", self.folder, 2, directory=True)
        self._wizard_path_row(body, "Resultados", self.output, 3, directory=True)
        ttk.Label(
            body,
            text="Las facturas se procesan localmente y no se copian ni se suben a Internet.",
            foreground="#50627a",
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(14, 12))
        ttk.Button(
            body,
            text="Guardar y continuar",
            style="Action.TButton",
            command=lambda: self._finish_first_run(wizard),
        ).grid(row=5, column=2, sticky="e")
        body.columnconfigure(1, weight=1)
        wizard.protocol("WM_DELETE_WINDOW", lambda: self._finish_first_run(wizard))
        wizard.wait_visibility()
        wizard.focus_force()

    def _wizard_path_row(
        self, parent: ttk.Frame, label: str, variable: tk.StringVar, row: int, directory: bool
    ) -> None:
        ttk.Label(parent, text=label, width=11).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=variable, width=62).grid(row=row, column=1, sticky="ew", padx=8, pady=5)

        def choose() -> None:
            selected = filedialog.askdirectory(parent=parent, initialdir=variable.get()) if directory else ""
            if selected:
                variable.set(selected)

        ttk.Button(parent, text="Elegir...", command=choose).grid(row=row, column=2, pady=5)

    def _finish_first_run(self, wizard: tk.Toplevel) -> None:
        if self._save_settings(notify=False):
            wizard.destroy()
            self.status.set("Configuracion inicial guardada. Ya puedes actualizar tus facturas.")

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
        if not self._save_settings(notify=False):
            return
        folder = Path(self.folder.get())
        output = Path(self.output.get())
        offers_path = Path(self.offers_path.get())
        self._start_worker("Procesando facturas y comparando la oferta...")
        threading.Thread(target=self._process, args=(folder, output, offers_path), daemon=True).start()

    def _start_history(self) -> None:
        if not self._save_settings(notify=False):
            return
        folder = Path(self.folder.get())
        output = Path(self.output.get())
        self._start_worker("Actualizando el historico de facturas...")
        threading.Thread(target=self._history, args=(folder, output), daemon=True).start()

    def _history(self, folder: Path, output: Path) -> None:
        try:
            _json_path, html_path, history = write_history(
                folder, output, progress_callback=lambda *event: self._progress(output, *event)
            )
            self.report_paths["history"] = html_path
            stats = history["processing"]
            result = (
                f"Historico actualizado: {history['invoice_count']} facturas; "
                f"nuevas {stats['new_count']}, omitidas {stats['skipped_count']}, "
                f"errores {stats['error_count']}; alertas detectadas {len(history.get('alerts', []))}."
            )
            self.worker_events.put(("finish", (result, False)))
        except Exception as exc:
            self._write_log(output, f"ERROR | {exc}")
            self.worker_events.put(("finish", (f"Error al actualizar: {exc}", True)))

    def _start_search(self) -> None:
        if not self._save_settings(notify=False):
            return
        folder = Path(self.folder.get())
        output = Path(self.output.get())
        self._start_worker("Consultando tarifas publicas oficiales y comparando localmente...")
        threading.Thread(target=self._search, args=(folder, output), daemon=True).start()

    def _search(self, folder: Path, output: Path) -> None:
        try:
            _json_path, history_html, history = write_history(
                folder, output, progress_callback=lambda *event: self._progress(output, *event)
            )
            _offers, _comparison_json, comparison_html, comparison = search_compare_and_write(history, output)
            self.report_paths = {"history": history_html, "comparison": comparison_html}
            errors = comparison.get("search", {}).get("errors", [])
            result = f"Encontradas {len(comparison['offers'])} ofertas; fuentes con error: {len(errors)}. Informe preparado."
            self.worker_events.put(("finish", (result, False)))
        except Exception as exc:
            self._write_log(output, f"ERROR | {exc}")
            self.worker_events.put(("finish", (f"Error en la busqueda: {exc}", True)))

    def _process(self, folder: Path, output: Path, offers_path: Path) -> None:
        try:
            json_path, html_path, history = write_history(
                folder, output, progress_callback=lambda *event: self._progress(output, *event)
            )
            comparison_json, comparison_html, comparison = write_comparison(
                history, offers_path, output
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
            self.worker_events.put(("finish", (result, False)))
        except Exception as exc:
            self._write_log(output, f"ERROR | {exc}")
            self.worker_events.put(("finish", (f"Error: {exc}", True)))

    def _start_worker(self, message: str) -> None:
        self._set_busy(True)
        self.status.set(message)
        self.progress_value.set(0)
        self.progress_text.set("Preparando...")
        if not self._polling_events:
            self._polling_events = True
            self.after(100, self._poll_worker_events)

    def _poll_worker_events(self) -> None:
        try:
            while True:
                event, payload = self.worker_events.get_nowait()
                if event == "progress":
                    current, total, filename, state = payload
                    self.progress_value.set((current / total) * 100 if total else 0)
                    label = {
                        "processing": "Leyendo",
                        "processed": "Procesada",
                        "skipped": "Ya estaba procesada",
                        "error": "Error",
                    }[state]
                    self.progress_text.set(f"{current}/{total} · {label}: {filename}")
                elif event == "finish":
                    message, error = payload
                    self._polling_events = False
                    self._finish(message, error=error)
                    return
        except queue.Empty:
            pass
        self.after(100, self._poll_worker_events)

    def _progress(self, output: Path, current: int, total: int, filename: str, state: str) -> None:
        self.worker_events.put(("progress", (current, total, filename, state)))
        self._write_log(output, f"{state.upper()} | {current}/{total} | {filename}")

    @staticmethod
    def _write_log(output: Path, message: str) -> None:
        output.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with (output / "procesamiento.log").open("a", encoding="utf-8") as stream:
            stream.write(f"{timestamp} | {message}\n")

    def _finish(self, message: str, error: bool = False) -> None:
        self._set_busy(False)
        self.status.set(message)
        if not error:
            self.progress_value.set(100)
            self.progress_text.set("Proceso terminado.")
        if error:
            messagebox.showerror("No se pudo procesar", message)

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.process_button.configure(state=state)
        self.search_button.configure(state=state)
        self.history_button.configure(state=state)

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
