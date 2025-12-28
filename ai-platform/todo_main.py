"""Main FastAPI application for the todo API."""

from fastapi import FastAPI

from api.routes import router as api_router

app = FastAPI(
    title="Todo API",
    description="A simple todo management API with CRUD operations",
    version="1.0.0",
)


@app.get("/")
def root() -> dict[str, str]:
    """Root endpoint with basic API info."""
    return {
        "message": "Todo API",
        "endpoints": "/api/todos",
    }


app.include_router(api_router, prefix="/api")
app.include_router(api_router)
