from __future__ import annotations

import tomllib
from urllib.parse import urlsplit
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


def check_url(url) -> None:
    """https only; plain http is allowed solely for localhost / 127.0.0.1."""
    try:
        u = urlsplit(url)
        host = u.hostname
    except (ValueError, AttributeError):
        raise ConfigError("[loopboard] url is invalid") from None
    if u.scheme == "https" and host:
        return
    if u.scheme == "http" and host in ("localhost", "127.0.0.1"):
        return
    raise ConfigError("[loopboard] url must be https (http only for localhost or 127.0.0.1)")
