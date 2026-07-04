from fastapi import FastAPI

from .db import init_db
from .routes import convert, documents, health, status

app = FastAPI(title="vid2doc API")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


app.include_router(health.router)
app.include_router(convert.router)
app.include_router(status.router)
app.include_router(documents.router)
