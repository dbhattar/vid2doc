from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import api_keys
from ..deps import get_current_session_user, get_current_user

router = APIRouter()


class CreateApiKeyRequest(BaseModel):
    name: str


@router.post("/api/keys", status_code=201)
def create_key(body: CreateApiKeyRequest, current_user: dict = Depends(get_current_session_user)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    key_dict, raw_key = api_keys.create_api_key(current_user["id"], name)
    # `key` is only ever present in this one response -- callers must save it now.
    return {**key_dict, "key": raw_key}


@router.get("/api/keys")
def list_keys(current_user: dict = Depends(get_current_user)):
    return {"keys": api_keys.list_api_keys_for_user(current_user["id"])}


@router.delete("/api/keys/{key_id}", status_code=204)
def revoke_key(key_id: str, current_user: dict = Depends(get_current_user)):
    if not api_keys.revoke_api_key(current_user["id"], key_id):
        raise HTTPException(status_code=404, detail="API key not found")
