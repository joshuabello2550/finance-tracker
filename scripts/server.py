"""FastAPI server for finance tracker."""

from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from helper import parse_csv_content, get_sheets_service
from import_transactions import (
    group_transactions_by_month,
    process_month,
    SPREADSHEET_ID,
    SHEET_NAME,
)

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/import")
async def import_transactions_endpoint(file: UploadFile):
    """Import transactions from uploaded CSV."""
    if not file.filename or not file.filename.endswith('.csv'):
        raise HTTPException(400, "File must be a CSV")

    try:
        content = (await file.read()).decode('utf-8')
        transactions = parse_csv_content(content)

        if not transactions:
            return {"total_added": 0, "months": []}

        by_month = group_transactions_by_month(transactions)
        service = get_sheets_service()

        results = []
        total_added = 0

        for month in sorted(by_month.keys()):
            added = process_month(service, SPREADSHEET_ID, SHEET_NAME, month, by_month[month])
            results.append({"month": month, "added": added})
            total_added += added

        return {
            "total_added": total_added,
            "months": results
        }

    except Exception as e:
        raise HTTPException(500, str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
