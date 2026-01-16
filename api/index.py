"""FastAPI server for finance tracker."""

from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow
from google.auth.transport import requests as google_requests
from google.oauth2.credentials import Credentials
import json

from .utils.helper import parse_csv_content
from .utils.import_transactions import process_all_transactions
import os

load_dotenv()

app = FastAPI(root_path="/api")

backend_url = os.getenv("BACKEND_URL")
frontend_url = os.getenv("FRONTEND_URL")

origins = []

if os.getenv("ENV") == "development":
    origins = [frontend_url]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OAuth Configuration
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid"
]


def get_oauth_flow():
    """Create OAuth flow instance."""
    redirect_uri = f"{backend_url}/api/auth/callback"

    client_config = {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri]
        }
    }

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    return flow


@app.get("/")
def read_root():
    return {"Python": "on Vercel"}


@app.get("/auth/google")
def google_auth():
    """Initiate Google OAuth flow."""
    flow = get_oauth_flow()
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"  # Force consent to get refresh token
    )

    return RedirectResponse(authorization_url)


@app.get("/auth/callback")
def google_callback(code: str = None, error: str = None):
    """Handle OAuth callback from Google."""
    import urllib.parse

    # Determine frontend URL based on environment
    if error:
        # Redirect to frontend with error
        return RedirectResponse(f"{frontend_url}/?auth_error={urllib.parse.quote(error)}")

    if not code:
        return RedirectResponse(f"{frontend_url}/?auth_error=no_code")

    try:
        flow = get_oauth_flow()
        flow.fetch_token(code=code)

        credentials = flow.credentials

        # Get user info to verify email
        import requests
        userinfo_response = requests.get(
            "https://www.googleapis.com/oauth2/v1/userinfo",
            headers={"Authorization": f"Bearer {credentials.token}"}
        )

        if userinfo_response.status_code != 200:
            return RedirectResponse(f"{frontend_url}/?auth_error=failed_user_info")

        user_info = userinfo_response.json()

        # Encode user data
        user_data = {
            "email": user_info.get("email"),
            "name": user_info.get("name"),
            "picture": user_info.get("picture")
        }

        # URL encode the data to pass to frontend
        params = {
            "access_token": credentials.token,
            "expiry": credentials.expiry.isoformat() if credentials.expiry else "",
            "user": json.dumps(user_data)
        }

        query_string = urllib.parse.urlencode(params)
        redirect_url = f"{frontend_url}/?{query_string}"

        return RedirectResponse(redirect_url)

    except Exception as e:
        return RedirectResponse(f"{frontend_url}/?auth_error={urllib.parse.quote(str(e))}")


@app.get("/auth/status")
def auth_status():
    """Check authentication status."""
    env = os.getenv("ENV", "production")

    if env == "development":
        return {
            "authenticated": True,
            "method": "service_account",
            "message": "Using credentials.json"
        }

    has_oauth = all([
        os.getenv("GOOGLE_CLIENT_ID"),
        os.getenv("GOOGLE_CLIENT_SECRET"),
        os.getenv("GOOGLE_REFRESH_TOKEN")
    ])

    return {
        "authenticated": has_oauth,
        "method": "oauth" if has_oauth else "none",
        "message": "OAuth configured" if has_oauth else "OAuth not configured"
    }


@app.get("/health")
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
        return process_all_transactions(transactions)

    except Exception as e:
        raise HTTPException(500, str(e))
