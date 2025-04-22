import uvicorn

if __name__ == "__main__":
    # Uvicorn serves FastAPI, which in turn spins up the bot
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
