from datetime import datetime
import google.auth
from dotenv import load_dotenv
from googleapiclient.discovery import build
import csv

load_dotenv()


def get_sheets_service():
    """Initialize Google Sheets API service."""
    creds, _ = google.auth.default()
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
    """Format amount as $X.XX (positive)."""
    return f"${abs(amount):.2f}"


def load_csv(file_path: str) -> list[dict]:
    """Read CSV and return list of purchase transactions (negative amounts only)."""
    transactions = []

    with open(file_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            amount = float(row['Amount'].replace('"', ''))

            # Only keep purchases (negative amounts), skip payments
            if amount >= 0:
                continue

            transactions.append({
                'date': row['Date'],
                'name': row['Name'].strip(),
                'amount': amount
            })

    return transactions


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
