from __future__ import annotations

import tomllib
from collections.abc import Mapping

from .contract import ConfigError


def load_config(path) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except OSError as e:
        raise ConfigError(f"cannot read config: {e.strerror or e}") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid config: {e}") from None


def resolve_token(cfg: dict, env: Mapping[str, str]) -> str:
    name = cfg.get("loopboard", {}).get("token_env")
    if not name:
        raise ConfigError("token_env is not configured")
    token = env.get(name)
    if not token:
        raise ConfigError("token environment variable is not set")
    return token
