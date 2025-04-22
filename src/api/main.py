from fastapi import FastAPI
from api.routes import users, upload
from api.db.db import init_db

app = FastAPI()

app.include_router(users.router, prefix="/users", tags=["Users"])
app.include_router(upload.router, prefix="/upload", tags=["Upload"])

@app.on_event("startup")
async def on_startup():
    await init_db()
