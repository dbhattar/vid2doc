from fastapi import APIRouter, Depends, HTTPException
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from pydantic import BaseModel

from .. import tokens, users
from ..config import settings
from ..deps import get_current_user

router = APIRouter()

_google_request = google_requests.Request()


class GoogleLoginRequest(BaseModel):
    id_token: str


@router.post("/api/auth/google")
def login_with_google(body: GoogleLoginRequest):
    try:
        payload = google_id_token.verify_oauth2_token(
            body.id_token, _google_request, settings.GOOGLE_CLIENT_ID
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google ID token")

    user = users.get_or_create_user_by_google(
        google_sub=payload["sub"],
        email=payload["email"],
        display_name=payload.get("name"),
        avatar_url=payload.get("picture"),
    )
    access_token = tokens.create_session_token(user["id"])
    return {"access_token": access_token, "user": user}


@router.get("/api/auth/me")
def get_me(current_user: dict = Depends(get_current_user)):
    return current_user
