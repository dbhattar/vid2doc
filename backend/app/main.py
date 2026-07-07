from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routes import auth, billing, convert, documents, health, jobs, keys, status

app = FastAPI(title="Framewrite API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(keys.router)
app.include_router(billing.router)
app.include_router(convert.router)
app.include_router(status.router)
app.include_router(jobs.router)
app.include_router(documents.router)
