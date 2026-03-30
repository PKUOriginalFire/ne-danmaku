"""WSGI/ASGI entrypoint."""

from nekocast_danmaku.app import create_app
from nekocast_danmaku.config import load_config
from nekocast_danmaku.runner import run_asgi


app = create_app(load_config())


if __name__ == "__main__":
    config = load_config()
    run_asgi(app, host=config.host, port=config.port, log_level="info")