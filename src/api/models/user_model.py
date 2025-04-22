from pydantic import BaseModel

class User(BaseModel):
    id: str
    name: str
    photo_url: str
    age: int
    city: str
    description: str
    age_filter: tuple[int, int]
    gender: str
    gender_filter: str
