"""Transaction categorization using Claude with enforced category enums."""

import json
from textwrap import dedent

import anthropic

from .helper import get_sheets_service, find_expense_section


def fetch_historical_expenses(spreadsheet_id: str, worksheet_name: str) -> list[dict]:
    """Fetch historical expense entries (name + category) from the given year's sheet."""
    service = get_sheets_service()

    month_columns = {
        1: "A:D", 2: "E:H", 3: "I:L", 4: "M:P", 5: "Q:T", 6: "U:X",
        7: "Y:AB", 8: "AC:AF", 9: "AG:AJ", 10: "AK:AN", 11: "AO:AR", 12: "AS:AV"
    }

    historical = []

    for col_range in month_columns.values():
        try:
            result = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=f"{worksheet_name}!{col_range}"
            ).execute()
            values = result.get('values', [])

            in_expense_section = False
            for row in values:
                if len(row) >= 3 and row[0] == "Date" and row[2] == "Expense":
                    in_expense_section = True
                    continue
                if in_expense_section:
                    if len(row) >= 1 and row[0] == "Total":
                        break
                    if len(row) >= 4 and row[2] and row[3]:
                        historical.append({
                            "expense_name": row[2],
                            "category": row[3]
                        })
        except Exception:
            continue

    seen = set()
    unique = []
    for entry in historical:
        if entry["expense_name"] not in seen:
            seen.add(entry["expense_name"])
            unique.append(entry)

    return unique


def fetch_categories(spreadsheet_id: str, worksheet_name: str) -> list[str]:
    """Fetch valid categories from the expense dropdown in column D."""
    service = get_sheets_service()

    values_response = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{worksheet_name}!A:D",
    ).execute()
    values = values_response.get("values", [])
    header_row, _ = find_expense_section(values)

    category_row = header_row + 2
    range_name = f"{worksheet_name}!D{category_row}:D{category_row}"

    response = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        includeGridData=True,
        ranges=range_name,
    ).execute()

    try:
        cell = response["sheets"][0]["data"][0]["rowData"][0]["values"][0]
        validation = cell["dataValidation"]
        if validation["condition"]["type"] != "ONE_OF_LIST":
            raise ValueError(f"Cell {range_name} is not a dropdown")
        return [v.get("userEnteredValue", "") for v in validation["condition"]["values"]]
    except (KeyError, IndexError, TypeError):
        raise ValueError("Invalid response structure or missing dropdown data")


def categorize(
    transactions: list[str],
    valid_categories: list[str],
    historical_expenses: list[dict] | None = None,
) -> list[dict]:
    """Categorize transactions using Claude with structured outputs."""
    if not transactions:
        return []

    schema = {
        "type": "object",
        "properties": {
            "transactions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "actual_name": {"type": "string"},
                        "expense_name": {"type": "string"},
                        "category": {"type": "string", "enum": valid_categories},
                    },
                    "required": ["actual_name", "expense_name", "category"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["transactions"],
        "additionalProperties": False,
    }

    historical_context = ""
    if historical_expenses:
        examples = historical_expenses[:50]
        historical_context = dedent(f"""
            HISTORICAL EXAMPLES (use these as reference for naming and categorization):
            {json.dumps(examples, indent=2)}
        """)

    prompt = dedent(f"""
        Categorize these transactions.

        VALID CATEGORIES (must use exactly one):
        {json.dumps(valid_categories)}
        {historical_context}
        TRANSACTIONS TO CATEGORIZE:
        {json.dumps(transactions)}

        Return actual_name (exact original), expense_name (short readable name), and category.

        IMPORTANT:
        - Use the historical examples to inform your naming
        - If you are unsure about the category for a transaction, use "NEED MANUAL ENTRY" instead of guessing.
    """)

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model="claude-haiku-4-5",
        max_tokens=4096,
        betas=["structured-outputs-2025-11-13"],
        messages=[{"role": "user", "content": prompt}],
        output_format={"type": "json_schema", "schema": schema},
    )

    result = json.loads(response.content[0].text)
    return result["transactions"]
