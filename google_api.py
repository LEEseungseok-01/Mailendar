# -*- coding: utf-8 -*-

import os
from typing import Any

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from config import BASE_DIR, GOOGLE_CLIENT_SECRETS_FILE, SCOPES, TOKEN_DIR


def get_google_service(api_name: str, api_version: str) -> Any:
    """Return an authenticated Google API service.

    Tokens are cached per api_name in TOKEN_DIR.
    """

    secret_path = GOOGLE_CLIENT_SECRETS_FILE or "credentials.json"
    if not os.path.isabs(secret_path):
        secret_path = os.path.join(BASE_DIR, secret_path)

    if not os.path.exists(secret_path):
        raise FileNotFoundError(f"Google client secrets file not found: {secret_path}")

    token_path = os.path.join(TOKEN_DIR, f"token_{api_name}.json")
    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
            # If you're running on remote server and browser can't open, replace with run_console()
            creds = flow.run_local_server(port=0)

        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build(api_name, api_version, credentials=creds)
