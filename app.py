"""瞭望与问数系统 v0.3 的 Tornado 应用入口。"""

from __future__ import annotations

import tornado.ioloop
import tornado.web
from tornado.httpserver import HTTPServer

from app.controllers.auth import (
    AdminLoginHandler,
    AdminLogoutHandler,
    RegisterHandler,
    UserLoginHandler,
    UserLogoutHandler,
)
from app.controllers.home import (
    AdminIndexHandler,
    UserChatHandler,
    UserChatStreamHandler,
    UserConversationHandler,
    UserIndexHandler,
)
from app.controllers.lookout import AdminLookoutCollectHandler, AdminLookoutHandler
from app.controllers.model_engine import AdminModelChatHandler, AdminModelsHandler
from app.controllers.digital_employee import (
    AdminDigitalEmployeePreviewHandler,
    AdminDigitalEmployeesHandler,
)
from app.controllers.sources import AdminSourcesHandler
from app.controllers.warehouse import (
    AdminWarehouseDeepCollectHandler,
    AdminWarehouseDeepResultHandler,
    AdminWarehouseDeepTaskHandler,
    AdminWarehouseHandler,
    AdminWarehouseImportHandler,
)
from app.controllers.admin import (
    AdminFeaturesHandler,
    AdminMenusHandler,
    AdminModuleHandler,
    AdminRolesHandler,
    AdminUsersHandler,
)
from app.models.db import init_db
from app.models.deep_collection import DeepCollectionRepository
from app.models.user import UserRepository
from config.settings import (
    APP_PORT,
    BASE_DIR,
    COOKIE_SECRET,
    DEBUG,
)


def make_app() -> tornado.web.Application:
    """创建应用并集中声明路由、安全和资源配置。"""
    return tornado.web.Application(
        [
            (r"/", UserLoginHandler),
            (r"/login", UserLoginHandler),
            (r"/register", RegisterHandler),
            (r"/index", UserIndexHandler),
            (r"/api/chat", UserChatHandler),
            (r"/api/chat/stream", UserChatStreamHandler),
            (r"/api/conversations/([0-9]+)", UserConversationHandler),
            (r"/logout", UserLogoutHandler),
            (r"/admin/?", AdminIndexHandler),
            (r"/admin/login", AdminLoginHandler),
            (r"/admin/logout", AdminLogoutHandler),
            (r"/admin/users", AdminUsersHandler),
            (r"/admin/roles", AdminRolesHandler),
            (r"/admin/features", AdminFeaturesHandler),
            (r"/admin/menus", AdminMenusHandler),
            (r"/admin/lookout", AdminLookoutHandler),
            (r"/admin/lookout/collect", AdminLookoutCollectHandler),
            (r"/admin/sources", AdminSourcesHandler),
            (r"/admin/warehouse", AdminWarehouseHandler),
            (r"/admin/warehouse/import", AdminWarehouseImportHandler),
            (r"/admin/warehouse/deep-collect", AdminWarehouseDeepCollectHandler),
            (r"/admin/warehouse/deep-tasks/([0-9]+)", AdminWarehouseDeepTaskHandler),
            (r"/admin/warehouse/deep-results/([0-9]+)", AdminWarehouseDeepResultHandler),
            (r"/admin/models", AdminModelsHandler),
            (r"/admin/models/chat", AdminModelChatHandler),
            (r"/admin/agents", AdminDigitalEmployeesHandler),
            (r"/admin/agents/preview", AdminDigitalEmployeePreviewHandler),
            (r"/admin/modules/agents", tornado.web.RedirectHandler, {"url": "/admin/agents", "permanent": True}),
            (r"/admin/modules/([a-z]+)", AdminModuleHandler),
        ],
        template_path=str(BASE_DIR / "app" / "templates"),
        static_path=str(BASE_DIR / "app" / "static"),
        cookie_secret=COOKIE_SECRET,
        login_url="/",
        xsrf_cookies=True,
        debug=DEBUG,
        autoreload=DEBUG,
    )


def prepare_runtime() -> bool:
    """初始化数据库并确保课堂演示管理员存在。"""
    init_db()
    DeepCollectionRepository.recover_interrupted()
    return UserRepository.ensure_admin("admin", "123456")


def main() -> None:
    admin_created = prepare_runtime()
    server = HTTPServer(make_app())
    server.listen(APP_PORT)
    print("=" * 62, flush=True)
    print("  瞭望与问数系统 DataFinderAgentOS v0.3", flush=True)
    print(f"  用户端: http://localhost:{APP_PORT}/", flush=True)
    print(f"  管理端: http://localhost:{APP_PORT}/admin/login", flush=True)
    if admin_created:
        print("  已创建演示管理员: admin / 123456", flush=True)
    print("=" * 62, flush=True)
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
