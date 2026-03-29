from __future__ import annotations

from pathlib import Path
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver
from watchdog.events import FileSystemEventHandler

from loguru import logger

from .models import BlacklistService

class _BlacklistFileHandler(FileSystemEventHandler):
    """
    处理黑名单文件的文件系统事件。

    参数:
        service (BlacklistService): 黑名单服务实例。
        pattern_file (Path): 模式文件的路径。
        user_file (Path): 用户文件的路径。
    """

    def __init__(
        self,
        service: BlacklistService,
        pattern_file: Path,
        user_file: Path,
    ):
        self.service = service  # 初始化黑名单服务
        self.pattern_file = pattern_file  # 初始化模式文件路径
        self.user_file = user_file  # 初始化用户文件路径

    def on_modified(self, event):
        """
        当监视的文件被修改时调用。

        参数:
            event (FileSystemEvent): 文件系统事件对象。
        """
        path = Path(event.src_path)  # 获取被修改的文件路径

        # 检查被修改的文件是否为黑名单文件之一
        if path == self.pattern_file or path == self.user_file:
            logger.info("Blacklist file changed: {}", path.name)  # 记录文件修改日志
            self.service.reload(self.pattern_file, self.user_file)  # 重新加载黑名单文件


def start_blacklist_watcher(
    service: BlacklistService,
    pattern_file: Path,
    user_file: Path,
) -> None:
    handler = _BlacklistFileHandler(service, pattern_file, user_file)

    observer = Observer()
    observer.schedule(handler, pattern_file.parent, recursive=False)
    observer.start()

    logger.info("Started blacklist watcher")
    
    service.watchdog = observer