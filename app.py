"""零界 v0.3 的 Tornado 应用入口。"""

from __future__ import annotations

import logging

import tornado.ioloop
import tornado.web
from tornado.httpserver import HTTPServer

from app.controllers.admin import (
    AdminFeaturesHandler,
    AdminMenusHandler,
    AdminModuleHandler,
    AdminRolesHandler,
    AdminSettingsHandler,
    AdminUsersHandler,
)
from app.controllers.admin.opinion import (
    AdminOpinionAlertsHandler,
    AdminSensitiveWordsHandler,
)
from app.controllers.admin.sessions import (
    AdminConversationPdfExportHandler,
    AdminMessagesHandler,
    AdminSessionsHandler,
)
from app.controllers.auth import (
    AdminLoginHandler,
    AdminLogoutHandler,
    RegisterHandler,
    UserLoginHandler,
    UserLogoutHandler,
)
from app.controllers.biometrics import (
    AdminFaceSettingHandler,
    FaceLoginHandler,
    FaceProfileHandler,
    GestureRecognizeHandler,
)
from app.controllers.dashboard import (
    AdminDashboardApiHandler,
    IntelligenceScreenApiHandler,
    IntelligenceScreenHandler,
    OpinionAlertActionHandler,
    OpinionScreenApiHandler,
    OpinionScreenHandler,
)
from app.controllers.digital_employee import (
    AdminDigitalEmployeePreviewHandler,
    AdminDigitalEmployeesHandler,
)
from app.controllers.export import ConversationPdfExportHandler
from app.controllers.home import (
    AdminIndexHandler,
    UserChatHandler,
    UserChatStreamHandler,
    UserConversationHandler,
    UserIndexHandler,
    UserUploadAssetHandler,
    UserUploadHandler,
)
from app.controllers.interface import (
    AdminInterfaceLogsHandler,
    AdminInterfacesHandler,
    AdminInterfaceTestHandler,
)
from app.controllers.lookout import (
    AdminLookoutCollectHandler,
    AdminLookoutHandler,
    AdminLookoutTaskActionHandler,
    AdminLookoutTaskHandler,
)
from app.controllers.model_engine import (
    AdminModelChatHandler,
    AdminModelsHandler,
    AdminModelUsageLogsHandler,
)
from app.controllers.multimodal import (
    AdminMultimodalConfigHandler,
    AdminMultimodalGenerateHandler,
    AdminMultimodalHandler,
    AdminMultimodalTaskDeleteHandler,
    AdminMultimodalTaskListHandler,
    AdminMultimodalTaskStatusHandler,
    MultimodalAssetHandler,
    UserMultimodalGenerateHandler,
    UserMultimodalTaskStatusHandler,
)
from app.controllers.skill import (
    AdminSkillBindHandler,
    AdminSkillsHandler,
    AdminSkillSuggestHandler,
)
from app.controllers.sources import AdminSourcesHandler
from app.controllers.tts import (
    AdminTTSHandler,
    AdminTTSPreviewHandler,
    TTSAudioHandler,
    UserTTSHandler,
)
from app.controllers.warehouse import (
    AdminWarehouseBatchDeleteHandler,
    AdminWarehouseDeduplicationHandler,
    AdminWarehouseDeepCollectHandler,
    AdminWarehouseDeepResultHandler,
    AdminWarehouseDeepTaskHandler,
    AdminWarehouseExportHandler,
    AdminWarehouseHandler,
    AdminWarehouseHighRiskHandler,
    AdminWarehouseImportHandler,
    AdminWarehouseRecollectHandler,
    AdminWarehouseRiskAnalysisHandler,
    WarehouseStatsHandler,
)
from app.core.logging import configure_logging
from app.models.db import init_db
from app.models.deep_collection import DeepCollectionRepository
from app.models.user import UserRepository
from app.services.collection_task import CollectionTaskService
from config.settings import BASE_DIR, SETTINGS

LOGGER = logging.getLogger("app")


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
            (r"/api/uploads", UserUploadHandler),
            (r"/api/uploads/([0-9]+)/([\w.-]+)", UserUploadAssetHandler),
            (r"/api/auth/face-login", FaceLoginHandler),
            (r"/api/profile/face", FaceProfileHandler),
            (r"/api/gestures/recognize", GestureRecognizeHandler),
            (r"/api/conversations/([0-9]+)", UserConversationHandler),
            (r"/api/conversations/([0-9]+)/export\.pdf", ConversationPdfExportHandler),
            (r"/logout", UserLogoutHandler),
            (r"/admin/?", AdminIndexHandler),
            (r"/api/admin/dashboard", AdminDashboardApiHandler),
            (r"/admin/login", AdminLoginHandler),
            (r"/admin/logout", AdminLogoutHandler),
            (r"/admin/users", AdminUsersHandler),
            (r"/api/admin/face-settings", AdminFaceSettingHandler),
            (r"/admin/roles", AdminRolesHandler),
            (r"/admin/features", AdminFeaturesHandler),
            (r"/admin/menus", AdminMenusHandler),
            (r"/admin/lookout", AdminLookoutHandler),
            (r"/admin/lookout/collect", AdminLookoutCollectHandler),
            (r"/admin/lookout/tasks/([0-9]+)", AdminLookoutTaskHandler),
            (r"/admin/lookout/tasks/([0-9]+)/(cancel|retry)", AdminLookoutTaskActionHandler),
            (r"/admin/sources", AdminSourcesHandler),
            (r"/admin/warehouse", AdminWarehouseHandler),
            (r"/admin/warehouse/export", AdminWarehouseExportHandler),
            (r"/admin/warehouse/import", AdminWarehouseImportHandler),
            (r"/admin/warehouse/([0-9]+)/recollect", AdminWarehouseRecollectHandler),
            (r"/admin/warehouse/deep-collect", AdminWarehouseDeepCollectHandler),
            (r"/admin/warehouse/deep-tasks/([0-9]+)", AdminWarehouseDeepTaskHandler),
            (r"/admin/warehouse/deep-results/([0-9]+)", AdminWarehouseDeepResultHandler),
            (r"/api/warehouse/stats", WarehouseStatsHandler),
            (r"/admin/warehouse/risk-analysis", AdminWarehouseRiskAnalysisHandler),
            (r"/admin/warehouse/high-risk", AdminWarehouseHighRiskHandler),
            (r"/admin/warehouse/batch-delete", AdminWarehouseBatchDeleteHandler),
            (r"/admin/warehouse/deduplication", AdminWarehouseDeduplicationHandler),
            (r"/admin/models", AdminModelsHandler),
            (r"/admin/models/chat", AdminModelChatHandler),
            (r"/admin/models/usage-logs", AdminModelUsageLogsHandler),
            (r"/admin/agents", AdminDigitalEmployeesHandler),
            (r"/admin/agents/preview", AdminDigitalEmployeePreviewHandler),
            (r"/admin/screens/intelligence", IntelligenceScreenHandler),
            (r"/api/admin/screens/intelligence", IntelligenceScreenApiHandler),
            (r"/admin/screens/opinion", OpinionScreenHandler),
            (r"/api/admin/screens/opinion", OpinionScreenApiHandler),
            (r"/api/admin/opinion/alerts/([0-9]+)", OpinionAlertActionHandler),
            (r"/admin/modules/agents", tornado.web.RedirectHandler, {"url": "/admin/agents", "permanent": True}),
            (r"/admin/interfaces", AdminInterfacesHandler),
            (r"/admin/interfaces/test", AdminInterfaceTestHandler),
            (r"/admin/interfaces/([0-9]+)/logs", AdminInterfaceLogsHandler),
            (r"/admin/skills", AdminSkillsHandler),
            (r"/admin/skills/([0-9]+)/bind", AdminSkillBindHandler),
            (r"/admin/skills/suggest", AdminSkillSuggestHandler),
            (r"/admin/tts", AdminTTSHandler),
            (r"/admin/tts/preview", AdminTTSPreviewHandler),
            (r"/tts/audio/(.*)", TTSAudioHandler),
            (r"/api/tts", UserTTSHandler),
            (r"/admin/multimodal", AdminMultimodalHandler),
            (r"/admin/multimodal/config", AdminMultimodalConfigHandler),
            (r"/admin/multimodal/generate", AdminMultimodalGenerateHandler),
            (r"/admin/multimodal/tasks", AdminMultimodalTaskListHandler),
            (r"/admin/multimodal/tasks/([a-zA-Z0-9-]+)", AdminMultimodalTaskStatusHandler),
            (r"/admin/multimodal/tasks/([a-zA-Z0-9-]+)/delete", AdminMultimodalTaskDeleteHandler),
            (r"/api/multimodal/generate", UserMultimodalGenerateHandler),
            (r"/api/multimodal/tasks/([a-zA-Z0-9-]+)", UserMultimodalTaskStatusHandler),
            (r"/multimodal/assets/(.*)", MultimodalAssetHandler),
            (r"/admin/modules/([a-z]+)", AdminModuleHandler),
            (r"/admin/settings", AdminSettingsHandler),
            (r"/admin/sessions", AdminSessionsHandler),
            (r"/admin/sessions/([0-9]+)/export\.pdf", AdminConversationPdfExportHandler),
            (r"/admin/messages", AdminMessagesHandler),
            (r"/admin/opinion/alerts", AdminOpinionAlertsHandler),
            (r"/admin/opinion/words", AdminSensitiveWordsHandler),
        ],
        template_path=str(BASE_DIR / "app" / "templates"),
        static_path=str(BASE_DIR / "app" / "static"),
        cookie_secret=SETTINGS.cookie_secret,
        login_url="/",
        xsrf_cookies=SETTINGS.xsrf_cookies,
        debug=SETTINGS.debug,
        autoreload=False,
    )


def prepare_runtime() -> bool:
    """初始化数据库并确保课堂演示管理员存在。"""
    init_db()
    DeepCollectionRepository.recover_interrupted()
    CollectionTaskService.recover_interrupted()
    return UserRepository.ensure_admin("admin", "123456")


def main() -> None:
    configure_logging(SETTINGS)
    admin_created = prepare_runtime()
    server = HTTPServer(make_app(), max_buffer_size=SETTINGS.upload_size_limit)
    server.listen(SETTINGS.port, address=SETTINGS.host)
    CollectionTaskService.resume_pending_tasks()
    LOGGER.info("application started config=%s", SETTINGS.public_summary(), extra={"event": "application_started"})
    if admin_created:
        LOGGER.info("demo administrator created", extra={"event": "administrator_seeded"})
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
