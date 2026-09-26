from fastapi import FastAPI

from app.api.routes_chat import router as chat_router

app = FastAPI(title="KB Agent", version="0.1.0")
app.include_router(chat_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
