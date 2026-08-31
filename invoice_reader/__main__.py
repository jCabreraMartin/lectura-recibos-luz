import argparse
import json
from pathlib import Path

from .batch import write_history
from .reader import read_invoice


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extrae una factura electrica a un formato comun."
    )
    parser.add_argument("pdf", type=Path, nargs="?")
    parser.add_argument("--folder", type=Path, help="Procesa todos los PDF de una carpeta.")
    parser.add_argument("--output", "-o", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("salidas"))
    args = parser.parse_args()

    if bool(args.pdf) == bool(args.folder):
        parser.error("Indica un PDF o usa --folder, pero no ambas opciones.")

    if args.folder:
        json_path, html_path, history = write_history(args.folder, args.output_dir)
        print(
            f"Procesadas {history['invoice_count']} facturas.\n"
            f"Historico: {json_path}\nInforme: {html_path}"
        )
        return

    invoice = read_invoice(args.pdf)
    rendered = json.dumps(invoice, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()

