"""仓储层包入口。"""

from app.repositories.base import BaseRepository, build_page, paginate

__all__ = ["BaseRepository", "paginate", "build_page"]
