import argparse
import json
from pathlib import Path

from .reader import read_invoice


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extrae una factura electrica a un formato comun."
    )
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", "-o", type=Path)
    args = parser.parse_args()

    invoice = read_invoice(args.pdf)
    rendered = json.dumps(invoice, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()

