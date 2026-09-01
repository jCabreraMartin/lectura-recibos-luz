import argparse
import json
from pathlib import Path

from .batch import write_history
from .reader import read_invoice
from .market import search_compare_and_write
from .tariffs import write_comparison


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extrae una factura electrica a un formato comun."
    )
    parser.add_argument("pdf", type=Path, nargs="?")
    parser.add_argument("--folder", type=Path, help="Procesa todos los PDF de una carpeta.")
    parser.add_argument("--output", "-o", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("salidas"))
    parser.add_argument("--no-ocr", action="store_true", help="Desactiva el OCR automatico.")
    parser.add_argument("--ocr-language", help="Idioma de Tesseract, por ejemplo spa+eng.")
    parser.add_argument("--offers", type=Path, help="JSON privado con ofertas para comparar.")
    parser.add_argument("--search-offers", action="store_true", help="Busca y compara ofertas publicas actuales.")
    args = parser.parse_args()

    if bool(args.pdf) == bool(args.folder):
        parser.error("Indica un PDF o usa --folder, pero no ambas opciones.")
    if args.offers and args.search_offers:
        parser.error("Usa --offers o --search-offers, pero no ambas opciones.")

    if args.folder:
        json_path, html_path, history = write_history(
            args.folder,
            args.output_dir,
            use_ocr=not args.no_ocr,
            ocr_language=args.ocr_language,
        )
        stats = history["processing"]
        print(
            f"Historico: {history['invoice_count']} facturas. "
            f"Nuevas: {stats['new_count']}; actualizadas: {stats['updated_count']}; "
            f"indexadas: {stats['indexed_count']}; omitidas: {stats['skipped_count']}; "
            f"errores: {stats['error_count']}.\n"
            f"Historico: {json_path}\nInforme: {html_path}"
        )
        if args.offers:
            comparison_json, comparison_html, comparison = write_comparison(
                history, args.offers, args.output_dir
            )
            complete = sum(offer["status"] == "complete" for offer in comparison["offers"])
            print(
                f"Comparadas {len(comparison['offers'])} ofertas; completas: {complete}.\n"
                f"Comparacion: {comparison_json}\nInforme: {comparison_html}"
            )
        if args.search_offers:
            offers_json, comparison_json, comparison_html, comparison = search_compare_and_write(
                history, args.output_dir
            )
            print(
                f"Encontradas {len(comparison['offers'])} ofertas publicas.\n"
                f"Catalogo: {offers_json}\nComparacion: {comparison_json}\n"
                f"Informe: {comparison_html}"
            )
        return

    invoice = read_invoice(
        args.pdf, use_ocr=not args.no_ocr, ocr_language=args.ocr_language
    )
    rendered = json.dumps(invoice, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()

