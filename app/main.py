from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.db import engine
from app.config import DATABASE_URL

app = FastAPI(
    title="wyjazdy-blog backend",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Dev CORS — open; will restrict later in prod
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    """
    Returns basic service and DB health.
    - status: always "ok" if the app is up
    - db: "ok" if SELECT 1 passes; otherwise error class name
    """
    db_status = "ok"
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
    except Exception as e:
        db_status = f"error: {e.__class__.__name__}"
    return {
        "status": "ok",
        "db": db_status,
        "driver": "sqlalchemy+psycopg",
        "database_url_present": bool(DATABASE_URL),
    }

if __name__ == "__main__":
    import uvicorn
    # Local dev runner
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
