from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pypdfium2 as pdfium


class OcrUnavailableError(RuntimeError):
    pass


def find_tesseract() -> Path:
    configured = os.environ.get("TESSERACT_CMD")
    candidates = [
        Path(configured) if configured else None,
        Path(getattr(sys, "_MEIPASS", "")) / "tesseract/tesseract.exe"
        if getattr(sys, "frozen", False)
        else None,
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


def find_tessdata() -> Path | None:
    configured = os.environ.get("TESSDATA_PREFIX")
    candidates = [
        Path(configured) if configured else None,
        Path(getattr(sys, "_MEIPASS", "")) / "tesseract/tessdata"
        if getattr(sys, "frozen", False)
        else None,
        Path(os.environ.get("LOCALAPPDATA", "")) / "lectura-recibos-luz/tessdata",
    ]
    for candidate in candidates:
        if candidate and candidate.is_dir() and any(candidate.glob("*.traineddata")):
            return candidate
    return None


def _available_languages(command: Path, tessdata: Path | None = None) -> set[str]:
    arguments = [str(command), "--list-langs"]
    if tessdata:
        arguments.extend(["--tessdata-dir", str(tessdata)])
    result = subprocess.run(
        arguments,
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


def _choose_language(
    command: Path, requested: str | None, tessdata: Path | None = None
) -> str:
    available = _available_languages(command, tessdata)
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
    tessdata = find_tessdata()
    selected_language = _choose_language(command, language, tessdata)
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
                arguments = [
                    str(command),
                    str(image_path),
                    "stdout",
                    "-l",
                    selected_language,
                    "--psm",
                    "6",
                ]
                if tessdata:
                    arguments.extend(["--tessdata-dir", str(tessdata)])
                result = subprocess.run(
                    arguments,
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
