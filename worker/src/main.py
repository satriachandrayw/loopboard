from workers import asgi

from loopboard.app import build_app

app = build_app()


class Default(asgi.entrypoint(app)):
    pass
