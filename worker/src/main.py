from fastapi import FastAPI
from workers import asgi

from loopboard import __version__

app = FastAPI()


@app.get("/api/probe")
async def probe():
    return {"version": __version__}


class Default(asgi.entrypoint(app)):
    pass
