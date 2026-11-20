"""Export and Reporting Utilities for Application Tracker (CSV and Excel)."""
import io
from pathlib import Path
from typing import Any, Dict, List
import pandas as pd
from src.logger import get_logger

logger = get_logger("export_utils")

BASE_DIR = Path(__file__).resolve().parent.parent
EXPORT_DIR = BASE_DIR / "outputs" / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def applications_to_dataframe(applications: List[Dict[str, Any]]) -> pd.DataFrame:
    """Convert application records into a clean, user-friendly Pandas DataFrame."""
    if not applications:
        return pd.DataFrame(
            columns=[
                "ID",
                "Company",
                "Role",
                "Platform",
                "Application URL",
                "Applied Date",
                "Status",
                "Follow-Up Date",
                "Notes",
            ]
        )

    rows = []
    for app in applications:
        rows.append(
            {
                "ID": app.get("id", ""),
                "Company": app.get("company", ""),
                "Role": app.get("role", ""),
                "Platform": app.get("platform", ""),
                "Application URL": app.get("application_url", ""),
                "Applied Date": app.get("applied_date", ""),
                "Status": app.get("status", ""),
                "Follow-Up Date": app.get("follow_up_date", ""),
                "Notes": app.get("notes", ""),
            }
        )
    return pd.DataFrame(rows)


def export_applications_to_csv(applications: List[Dict[str, Any]], save_path: Path | None = None) -> bytes:
    """Export application tracker records to CSV bytes (and optionally save to disk)."""
    df = applications_to_dataframe(applications)
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    target = save_path or (EXPORT_DIR / "internship_applications.csv")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(csv_bytes)
    logger.info("Exported %d applications to CSV at %s", len(df), target)
    return csv_bytes


def export_applications_to_excel(applications: List[Dict[str, Any]], save_path: Path | None = None) -> bytes:
    """Export application tracker records to an Excel (.xlsx) workbook using openpyxl."""
    df = applications_to_dataframe(applications)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Applications Tracker")
    excel_bytes = buffer.getvalue()

    target = save_path or (EXPORT_DIR / "internship_applications.xlsx")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(excel_bytes)
    logger.info("Exported %d applications to Excel at %s", len(df), target)
    return excel_bytes
