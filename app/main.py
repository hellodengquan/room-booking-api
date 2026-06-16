from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.routers import auth, rooms, bookings, calendar, batch

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="会议室预订系统 API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event():
    init_db()


@app.get("/", tags=["根路径"])
async def root():
    return {
        "message": "会议室预订系统 API",
        "version": "1.0.0",
        "docs": "/docs",
        "api_prefix": settings.API_V1_STR,
    }


@app.get("/health", tags=["健康检查"])
async def health_check():
    return {"status": "healthy"}


app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(rooms.router, prefix=settings.API_V1_STR)
app.include_router(bookings.router, prefix=settings.API_V1_STR)
app.include_router(calendar.router, prefix=settings.API_V1_STR)
app.include_router(batch.router, prefix=settings.API_V1_STR)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
