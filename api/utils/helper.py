from datetime import datetime
from pathlib import Path
import io
import csv
import json
import os

from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from googleapiclient.discovery import build

load_dotenv()

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_sheets_service():
    """Initialize Google Sheets API service using a service account.

    Loads credentials from GOOGLE_SERVICE_ACCOUNT_JSON (raw JSON env var, for
    Vercel) when set, otherwise from credentials.json at the project root.
    """
    sa_json_env = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json_env:
        info = json.loads(sa_json_env)
        creds = Credentials.from_service_account_info(info, scopes=SHEETS_SCOPES)
    else:
        creds_path = Path(__file__).resolve().parents[2] / "credentials.json"
        creds = Credentials.from_service_account_file(str(creds_path), scopes=SHEETS_SCOPES)

    return build("sheets", "v4", credentials=creds)


def parse_date(date_str: str) -> tuple[int, int, int]:
    """Parse date string (YYYY-MM-DD) and return (year, month, day)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.year, dt.month, dt.day


def format_date_short(date_str: str) -> str:
    """Convert YYYY-MM-DD to M/D format."""
    _, month, day = parse_date(date_str)
    return f"{month}/{day}"


def format_amount(amount: float) -> str:
    """Format amount as $X,XXX.XX (positive, with thousands separator)."""
    return f"${abs(amount):,.2f}"


def parse_csv_content(content: str) -> list[dict]:
    """Parse CSV content string and return all transactions (both debits and credits)."""
    transactions = []
    reader = csv.DictReader(io.StringIO(content))

    for row in reader:
        amount = float(row['Amount'].replace('"', ''))
        transactions.append({
            'date': row['Date'],
            'name': row['Name'].strip(),
            'amount': amount,
            'txn_type': row.get('Transaction', '').strip().upper(),
        })

    return transactions


def load_csv(file_path: str) -> list[dict]:
    """Read CSV file and return all transactions."""
    with open(file_path, 'r', newline='', encoding='utf-8') as f:
        return parse_csv_content(f.read())


# Month to column mapping (0-indexed): Jan=A, Feb=E, Mar=I, etc.


def get_column_range(month: int) -> tuple[str, str]:
    MONTH_COLUMNS = {
        1: "A", 2: "E", 3: "I", 4: "M", 5: "Q", 6: "U",
        7: "Y", 8: "AC", 9: "AG", 10: "AK", 11: "AO", 12: "AS"
    }

    """Get the 4-column range for a given month (1-12)."""
    start_col = MONTH_COLUMNS[month]
    # Calculate end column (start + 3)
    if len(start_col) == 1:
        end_col = chr(ord(start_col) + 3)
    else:
        # Handle two-letter columns (AA, AB, etc.)
        end_col = start_col[0] + chr(ord(start_col[1]) + 3)
    return start_col, end_col


def find_expense_section(values: list[list]) -> tuple[int, int]:
    """
    Find the Expense section in the column data.
    Returns (header_row_index, last_expense_row_index).
    """
    expense_header_row = None
    last_expense_row = None

    for i, row in enumerate(values):
        # Look for the Expense header row
        if len(row) >= 3 and row[0] == "Date" and row[2] == "Expense":
            expense_header_row = i
            continue

        # If we found the header, look for expense entries
        if expense_header_row is not None and i > expense_header_row:
            # Check if this row has data (date in first column)
            if len(row) >= 1 and row[0] and row[0] != "Total":
                last_expense_row = i
            # If we hit "Total" or empty section, stop
            elif len(row) >= 1 and row[0] == "Total":
                break

    return expense_header_row, last_expense_row
