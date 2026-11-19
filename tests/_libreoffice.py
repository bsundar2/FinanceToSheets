"""LibreOffice helpers for the tests that check spreadsheet formulas: build a
workbook with openpyxl, have LibreOffice calculate it as Google Sheets would
on import, and read the values back. Skipped where libreoffice-calc isn't
installed."""

import shutil
import subprocess

import openpyxl


def _recalculate(wb, tmp_path):
    """Saves wb and has LibreOffice compute every formula, as Google Sheets
    would on import."""
    source = tmp_path / "in.xlsx"
    wb.save(source)
    subprocess.run(
        ["soffice", "--headless", "--norestore",
         f"-env:UserInstallation=file://{tmp_path}/profile",
         "--convert-to", "xlsx", "--outdir", str(tmp_path / "out"), str(source)],
        check=True, capture_output=True, timeout=300,
    )  # fmt: skip
    return openpyxl.load_workbook(tmp_path / "out" / "in.xlsx", data_only=True)


def _has_calc():
    if not shutil.which("soffice"):
        return False
    return any(
        "calc" in line
        for line in subprocess.run(
            ["dpkg", "-l"], capture_output=True, text=True, check=False
        ).stdout.splitlines()
        if "libreoffice-calc" in line
    )
