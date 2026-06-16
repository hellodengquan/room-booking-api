from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.routers import auth, rooms, bookings, calendar, batch, delegations, cancellations, advanced

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="会议室预订系统 API",
    version="2.2.0",
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
        "version": "2.2.0",
        "docs": "/docs",
        "api_prefix": settings.API_V1_STR,
        "features": [
            "多会议室多时段并发预订",
            "循环周期预订（日/周/双周/月）",
            "冲突检测与替代建议",
            "设备占用管理",
            "权限维度控制",
            "日历视图查询",
            "批量取消与回滚",
            "取消审批流程",
            "委托代订",
            "时区支持",
            "评分推荐算法",
            "循环预订跳过策略",
            "设备过滤与权重调参",
            "DST 夏令时处理与通知",
            "委托撤销与审计",
            "A/B 测试框架",
            "租户级配置",
            "校准样本管理",
            "取消快照留存",
            "模块覆盖率 SLA",
        ],
    }


@app.get("/health", tags=["健康检查"])
async def health_check():
    return {"status": "healthy", "version": "2.2.0"}


app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(rooms.router, prefix=settings.API_V1_STR)
app.include_router(bookings.router, prefix=settings.API_V1_STR)
app.include_router(calendar.router, prefix=settings.API_V1_STR)
app.include_router(batch.router, prefix=settings.API_V1_STR)
app.include_router(delegations.router, prefix=settings.API_V1_STR)
app.include_router(cancellations.router, prefix=settings.API_V1_STR)
app.include_router(advanced.router, prefix=settings.API_V1_STR)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
