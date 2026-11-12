import time

from workers import asgi

from loopboard import cron
from loopboard.app import build_app
from loopboard.db import Repo

app = build_app()


class Default(asgi.entrypoint(app)):
    # The SDK dispatches the JS handler `scheduled(controller)`; `self.env` carries the
    # bindings. `env`/`ctx` are accepted too in case a caller passes them.
    async def scheduled(self, controller=None, env=None, ctx=None):
        env = env if env is not None else self.env
        await cron.run_stall_transitions(Repo(env.DB), now=int(time.time()))
