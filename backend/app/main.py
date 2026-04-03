from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import jobs, videos
from .config import configure_logging, get_settings
from .models.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    configure_logging()
    settings = get_settings()

    settings.ensure_directories()

    init_db(settings.database_url)

    yield


app = FastAPI(
    title="Classic Car Analysis API",
    description="AI-powered pipeline for analyzing classic car videos",
    version="1.0.0",
    lifespan=lifespan,
)

settings = get_settings()
origins = settings.cors_origins.split(",") if settings.cors_origins != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(videos.router, prefix="/api/videos", tags=["videos"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/api/costs")
async def get_costs():
    """Get aggregate cost report"""
    from .models.db import Job, create_session_factory, get_engine

    settings = get_settings()
    engine = get_engine(settings.database_url)
    SessionLocal = create_session_factory(engine)

    with SessionLocal() as db:
        jobs_list = db.query(Job).all()
        total_cost = sum(j.cost or 0 for j in jobs_list)
        completed_jobs = [j for j in jobs_list if j.status == "complete"]

        return {
            "total_jobs": len(jobs_list),
            "completed_jobs": len(completed_jobs),
            "total_cost": total_cost,
            "jobs": [
                {
                    "id": j.id,
                    "filename": j.original_filename,
                    "cost": j.cost or 0,
                    "status": j.status
                }
                for j in jobs_list
            ]
        }
