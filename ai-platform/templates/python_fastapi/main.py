from fastapi import FastAPI

from api.routes import router as api_router

app = FastAPI()
app.include_router(api_router, prefix="/api")


@app.get("/")
def read_root():
    return {"status": "ok"}


@app.get("/health")
def read_health():
    return {"status": "ok"}
