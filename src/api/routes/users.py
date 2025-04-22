from fastapi import APIRouter
from pydantic import BaseModel
from uuid import uuid4
from api.db.db import UserDB

router = APIRouter()

class UserCreate(BaseModel):
    name: str
    photo_url: str
    age: int
    city: str
    description: str
    age_filter: tuple[int, int]
    gender: str
    gender_filter: str

@router.post("/")
async def create_user(user: UserCreate):
    user_id = str(uuid4())
    await UserDB.create_user(user_id, user)
    return {"status": "created", "user_id": user_id}
