from googleapiclient.errors import HttpError
from googleapiclient.discovery import build
import google.auth
import csv
import sys
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

SPREADSHEET_ID = "1R-LLdpkVxjewiRD6LNer7sUF_AtJfx1_b6G1VPddc9k"
SHEET_NAME = "2026"

# Month to column mapping (0-indexed): Jan=A, Feb=E, Mar=I, etc.
MONTH_COLUMNS = {
    1: "A", 2: "E", 3: "I", 4: "M", 5: "Q", 6: "U",
    7: "Y", 8: "AC", 9: "AG", 10: "AK", 11: "AO", 12: "AS"
}

# Category keyword mapping (case-insensitive matching)
# Note: Category names must match exactly what's in the sheet's dropdown
CATEGORY_KEYWORDS = {
    "Groceries": [
        "WHOLE FOODS", "TRADER JOE", "MARKET BASKET", "STOP & SHOP",
        "STAR MARKET", "WEGMANS", "ALDI", "COSTCO", "H MART", "SHAWS",
        "GROCERY", "SUPERMARKET", "H-E-B", "KROGER"
    ],
    "Snacks/Eating out": [
        "CHIPOTLE", "CAVA", "STARBUCKS", "DUNKIN", "MCDONALD", "BURGER",
        "PIZZA", "SUBWAY", "DOORDASH", "UBER EATS", "UBER   *EATS",
        "GRUBHUB", "SEAMLESS", "RESTAURANT", "CAFE", "COFFEE", "BAKERY",
        "TST*", "6AM HEALTH", "BAR", "PUB", "TAVERN", "CHICK-FIL-A"
    ],
    "Transportation": [
        "LYFT", "MBTA", "CHARLIE", "TRANSIT", "PARKING", "TOLL",
        "ZIPCAR", "SWA*", "SOUTHWEST", "AIRLINE", "FLIGHT",
        "GAS", "SHELL", "EXXON", "MOBIL", "CHEVRON"
    ],
    "Medical": [
        "CVS", "PHARMACY", "WALGREENS", "RITE AID", "HOSPITAL", "MEDICAL",
        "DOCTOR", "CLINIC", "DENTAL", "OPTOMETRY"
    ],
    "Laundry": [
        "CSC SERVICEWORKS", "LAUNDRY", "DRY CLEAN", "CLEANERS"
    ],
    "Clothing / Shoes": [
        "NIKE", "ADIDAS", "UNIQLO", "H&M", "ZARA", "GAP", "OLD NAVY",
        "NORDSTROM", "MACYS", "TJ MAXX", "MARSHALLS", "FOOTLOCKER", "DSW"
    ],
    "Housing": [
        "RENT", "UTILITIES", "ELECTRIC", "WATER", "INTERNET", "COMCAST",
        "VERIZON FIOS", "HOME DEPOT", "LOWES", "IKEA", "FURNITURE",
        "GOOGLE WORKSPACE"
    ],
    "Essential Miscellaneous": [
        "AMAZON", "OFFICE", "SUPPLIES"
    ],
    "Gift": [
        "GIFT", "FLOWERS", "CARD"
    ],
}


def get_column_range(month: int) -> tuple[str, str]:
    """Get the 4-column range for a given month (1-12)."""
    start_col = MONTH_COLUMNS[month]
    # Calculate end column (start + 3)
    if len(start_col) == 1:
        end_col = chr(ord(start_col) + 3)
    else:
        # Handle two-letter columns (AA, AB, etc.)
        end_col = start_col[0] + chr(ord(start_col[1]) + 3)
    return start_col, end_col


def categorize_transaction(name: str) -> str:
    """Auto-categorize transaction based on merchant name keywords."""
    name_upper = name.upper()

    # Check for UBER but not UBER EATS (transportation vs food)
    if "UBER" in name_upper and "EATS" not in name_upper:
        return "Transportation"

    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in name_upper:
                return category

    return "Non-essential Miscellaneous"


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


def get_sheets_service():
    """Initialize Google Sheets API service."""
    creds, _ = google.auth.default()
    return build("sheets", "v4", credentials=creds)


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


def get_existing_expenses(values: list[list], header_row: int | None, last_row: int | None) -> set[tuple]:
    """Extract existing expenses for duplicate checking (date, amount)."""
    existing = set()

    if header_row is None:
        return existing

    start = header_row + 1
    end = (last_row + 1) if last_row else start

    for i in range(start, end + 1):
        if i < len(values):
            row = values[i]
            if len(row) >= 2 and row[0] and row[0] != "Total":
                date = row[0]  # Already in M/D format
                amount = row[1]  # Already in $X.XX format
                existing.add((date, amount))

    return existing


def group_transactions_by_month(transactions: list[dict]) -> dict[int, list[dict]]:
    """Group transactions by month number."""
    by_month = defaultdict(list)
    for txn in transactions:
        _, month, _ = parse_date(txn['date'])
        by_month[month].append(txn)

    return dict(by_month)


def get_sheet_id(service, spreadsheet_id: str, sheet_name: str) -> int:
    """Get the sheet ID for a given sheet name."""
    spreadsheet = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id).execute()
    for sheet in spreadsheet['sheets']:
        if sheet['properties']['title'] == sheet_name:
            return sheet['properties']['sheetId']
    raise ValueError(f"Sheet '{sheet_name}' not found")


def rows_to_tsv(rows: list[list]) -> str:
    """Convert 2D array to tab-separated string."""
    return "\n".join("\t".join(str(cell) for cell in row) for row in rows)


def col_letter_to_index(col: str) -> int:
    """Convert column letter(s) to 0-based index. A=0, B=1, ..., Z=25, AA=26, etc."""
    result = 0
    for char in col:
        result = result * 26 + (ord(char.upper()) - ord('A') + 1)
    return result - 1


def get_validation_rule_from_cell(service, spreadsheet_id: str, sheet_name: str, cell: str) -> dict | None:
    """Fetch the data validation rule from an existing cell."""
    try:
        result = service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            ranges=[f"{sheet_name}!{cell}"],
            includeGridData=True
        ).execute()

        for sheet in result.get('sheets', []):
            for data in sheet.get('data', []):
                for row in data.get('rowData', []):
                    for cell_data in row.get('values', []):
                        validation = cell_data.get('dataValidation')
                        if validation:
                            return validation
        return None
    except HttpError as e:
        print(f"Error fetching validation rule: {e}")
        return None


def paste_rows(
    service, spreadsheet_id: str, sheet_id: int, sheet_name: str,
    start_col: str, row_start: int, rows: list[list], source_validation_cell: str
):
    """Paste data, apply non-bold formatting, and set validation - all in one batch."""
    col_start_index = col_letter_to_index(start_col)
    category_col_index = col_start_index + 3  # 4th column (Category)
    num_rows = len(rows)

    validation_rule = get_validation_rule_from_cell(
        service, spreadsheet_id, sheet_name, source_validation_cell
    )

    requests = [
        # 1. Paste data
        {
            "pasteData": {
                "coordinate": {
                    "sheetId": sheet_id,
                    "rowIndex": row_start,
                    "columnIndex": col_start_index
                },
                "data": rows_to_tsv(rows),
                "type": "PASTE_NORMAL",
                "delimiter": "\t"
            }
        },
    ]

    # 4. Set validation if we found a rule
    if validation_rule:
        requests.append({
            "setDataValidation": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": row_start,
                    "endRowIndex": row_start + num_rows,
                    "startColumnIndex": category_col_index,
                    "endColumnIndex": category_col_index + 1
                },
                "rule": validation_rule
            }
        })

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests}
    ).execute()


def process_month(service, spreadsheet_id: str, sheet_name: str, month: int, transactions: list[dict]):
    """Process transactions for a single month."""
    start_col, end_col = get_column_range(month)
    range_name = f"{sheet_name}!{start_col}:{end_col}"

    print(f"\nProcessing month {month} (columns {start_col}:{end_col})...")

    # Read current month data
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        values = result.get('values', [])
    except HttpError as e:
        print(f"Error reading sheet: {e}")
        return 0

    # Find expense section
    header_row, last_expense_row = find_expense_section(values)

    if header_row is None:
        print(f"  Could not find Expense section for month {month}")
        return 0

    print(f"  Found Expense header at row {header_row + 1}")
    if last_expense_row:
        print(f"  Last expense at row {last_expense_row + 1}")

    # Get existing expenses for dedup
    existing = get_existing_expenses(values, header_row, last_expense_row)
    print(f"  Found {len(existing)} existing expenses")

    # Filter duplicates and format new transactions
    new_rows = []
    for txn in transactions:
        date_short = format_date_short(txn['date'])
        amount_fmt = format_amount(txn['amount'])
        key = (date_short, amount_fmt)

        if key in existing:
            print(
                f"  Skipping duplicate: {date_short} {amount_fmt} {txn['name'][:30]}")
            continue

        category = categorize_transaction(txn['name'])
        new_rows.append([date_short, amount_fmt, txn['name'], category])
        print(
            f"  Adding: {date_short} | {amount_fmt:>10} | {txn['name'][:35]:<35} | {category}")

    if not new_rows:
        print(f"  No new transactions to add for month {month}")
        return 0

    # Calculate insert position (after last expense, or after header if no expenses)
    insert_row = (last_expense_row +
                  1) if last_expense_row else (header_row + 1)

    # Get sheet ID and source validation cell
    sheet_id = get_sheet_id(service, spreadsheet_id, sheet_name)
    category_col = chr(ord(start_col[0]) + 3) if len(
        start_col) == 1 else start_col[0] + chr(ord(start_col[1]) + 3)
    source_validation_cell = f"{category_col}{header_row + 2}"

    # Paste data, apply formatting and validation in one batch
    print(f"  Pasting {len(new_rows)} rows at row {insert_row + 1}...")
    paste_rows(
        service, spreadsheet_id, sheet_id, sheet_name,
        start_col, insert_row, new_rows, source_validation_cell
    )

    print(f"  Successfully added {len(new_rows)} transactions")
    return len(new_rows)


def main(csv_path: str):
    """Main entry point."""
    print(f"Reading CSV: {csv_path}")

    # Load transactions from CSV
    transactions = load_csv(csv_path)
    print(f"Found {len(transactions)} purchase transactions")

    if not transactions:
        print("No purchase transactions found in CSV")
        return

    # Group by month
    by_month = group_transactions_by_month(transactions)
    print("by_month: ", by_month)
    print(
        f"Transactions span {len(by_month)} month(s): {sorted(by_month.keys())}")

    # Initialize Google Sheets service
    service = get_sheets_service()

    # Process each month
    total_added = 0
    for month in sorted(by_month.keys()):
        added = process_month(service, SPREADSHEET_ID,
                              SHEET_NAME, month, by_month[month])
        total_added += added

    print(f"\n=== Done! Added {total_added} total transactions ===")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_transactions.py <csv_file_path>")
        sys.exit(1)

    main(sys.argv[1])
