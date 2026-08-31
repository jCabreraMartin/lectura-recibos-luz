from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pypdfium2 as pdfium


class OcrUnavailableError(RuntimeError):
    pass


def find_tesseract() -> Path:
    configured = os.environ.get("TESSERACT_CMD")
    candidates = [
        Path(configured) if configured else None,
        Path(shutil.which("tesseract") or "") if shutil.which("tesseract") else None,
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Tesseract-OCR/tesseract.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Tesseract-OCR/tesseract.exe",
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    raise OcrUnavailableError(
        "El PDF no contiene texto y Tesseract OCR no esta instalado. "
        "Instala Tesseract o define TESSERACT_CMD con la ruta del ejecutable."
    )


def _available_languages(command: Path) -> set[str]:
    result = subprocess.run(
        [str(command), "--list-langs"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.lower().startswith("list of available")
    }


def _choose_language(command: Path, requested: str | None) -> str:
    available = _available_languages(command)
    if requested:
        missing = set(requested.split("+")) - available
        if missing:
            raise OcrUnavailableError(
                "Tesseract no tiene instalados estos idiomas: " + ", ".join(sorted(missing))
            )
        return requested
    if "spa" in available and "eng" in available:
        return "spa+eng"
    if "spa" in available:
        return "spa"
    if "eng" in available:
        return "eng"
    if available:
        return sorted(available)[0]
    raise OcrUnavailableError("Tesseract no tiene ningun idioma instalado.")


def ocr_pdf(path: Path, language: str | None = None, scale: float = 2.5) -> list[str]:
    command = find_tesseract()
    selected_language = _choose_language(command, language)
    document = pdfium.PdfDocument(str(path))
    pages: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="lectura-recibos-ocr-") as temp:
            temp_dir = Path(temp)
            for index in range(len(document)):
                page = document[index]
                image_path = temp_dir / f"pagina-{index + 1}.png"
                bitmap = page.render(scale=scale)
                bitmap.to_pil().save(image_path, format="PNG")
                result = subprocess.run(
                    [
                        str(command),
                        str(image_path),
                        "stdout",
                        "-l",
                        selected_language,
                        "--psm",
                        "6",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=True,
                )
                pages.append(result.stdout)
                page.close()
    finally:
        document.close()
    return pages

