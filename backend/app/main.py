from fastapi import FastAPI

from .routes import convert, documents, health, status

app = FastAPI(title="vid2doc API")

app.include_router(health.router)
app.include_router(convert.router)
app.include_router(status.router)
app.include_router(documents.router)
