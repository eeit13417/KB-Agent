from fastapi import FastAPI
from app.api.routes_auth import router as auth_router
from app.api.routes_chat import router as chat_router
from pathlib import Path
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="KB Agent", version="0.1.0")
app.include_router(chat_router, prefix="/api")
app.include_router(auth_router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

# Only mounted when the frontend has been built; local dev uses the Vite server instead.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")