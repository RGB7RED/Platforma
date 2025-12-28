from fastapi import FastAPI

from api.routes import router

app = FastAPI()
app.include_router(router)


@app.get("/")
def read_root():
    return {"status": "ok"}


@app.get("/health")
def read_health():
    return {"status": "ok"}
