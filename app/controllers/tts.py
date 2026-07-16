"""语音合成配置与服务接口。"""

from __future__ import annotations

import os

import tornado

from app.controllers.base import AdminBaseHandler, AdminJsonHandler, UserJsonHandler
from app.models.tts import TTSCallRepository, TTSConfigRepository
from app.services.tts import TTSService, TTSServiceError

VOICE_OPTIONS = [
    ("zh_female", "中文女声"),
    ("zh_male", "中文男声"),
    ("zh_child", "中文童声"),
    ("zh_gentle", "中文温柔女声"),
    ("zh_intelligent", "中文知性女声"),
    ("zh_energetic", "中文活力女声"),
    ("zh_calm", "中文沉稳男声"),
    ("zh_youth", "中文年轻男声"),
    ("en_female", "英文女声"),
    ("en_male", "英文男声"),
    ("en_us_female", "英文美式女声"),
    ("en_us_male", "英文美式男声"),
    ("en_uk_female", "英文英式女声"),
    ("en_uk_male", "英文英式男声"),
    ("ja_female", "日语女声"),
    ("ja_male", "日语男声"),
    ("ko_female", "韩语女声"),
    ("ko_male", "韩语男声"),
]


class AdminTTSHandler(AdminBaseHandler):
    required_feature = "tts_config"

    def get(self):
        config = TTSConfigRepository.get_config()
        stats = TTSCallRepository.stats()
        self.render_admin(
            "admin/tts_config.html",
            title="语音合成配置 · 瞭望与问数系统",
            active_menu="tts_config",
            config=config,
            voice_options=VOICE_OPTIONS,
            stats=stats,
            can_write=True,
        )

    def post(self):
        action = self.get_body_argument("action", "")
        if action != "save":
            return self.redirect_with_message("/admin/tts", "未知操作", "error")
        try:
            enabled = self.get_body_argument("enabled", "0") == "1"
            provider = self.get_body_argument("provider", "volcengine")
            default_voice = self.get_body_argument("default_voice", "zh_female")
            api_key_env = self.get_body_argument("api_key_env", "")
            api_secret_env = self.get_body_argument("api_secret_env", "")
            base_url = self.get_body_argument("base_url", "")
            rate = int(self.get_body_argument("rate", "0"))
            volume = int(self.get_body_argument("volume", "0"))
            pitch = int(self.get_body_argument("pitch", "0"))
            if provider not in {"volcengine", "aliyun", "local"}:
                raise ValueError("不支持的 TTS 提供商")
            if default_voice not in [v[0] for v in VOICE_OPTIONS]:
                raise ValueError("无效的语音选择")
            TTSConfigRepository.update_config(
                enabled=enabled,
                provider=provider,
                default_voice=default_voice,
                api_key_env=api_key_env,
                api_secret_env=api_secret_env,
                base_url=base_url,
                rate=rate,
                volume=volume,
                pitch=pitch,
            )
            self.redirect_with_message("/admin/tts", "语音合成配置已更新", "success")
        except ValueError as exc:
            self.redirect_with_message("/admin/tts", str(exc), "error")


class AdminTTSPreviewHandler(AdminJsonHandler):
    required_feature = "model_engine"

    async def post(self):
        payload = self.json_body()
        text = str(payload.get("text", ""))
        voice = str(payload.get("voice", ""))
        if not 1 <= len(text) <= 5000:
            return self.write_json({"ok": False, "message": "文本长度需为 1—5000 个字符"}, 400)
        try:
            result = await TTSService.synthesize(text, voice)
            TTSCallRepository.record(
                text_length=len(text),
                voice=voice,
                success=True,
                from_cache=result.get("from_cache", False),
            )
            return self.write_json(result)
        except TTSServiceError as exc:
            TTSCallRepository.record(
                text_length=len(text),
                voice=voice,
                success=False,
                error_message=str(exc),
            )
            return self.write_json({"ok": False, "message": str(exc)}, 500)


class TTSAudioHandler(tornado.web.StaticFileHandler):
    def initialize(self):
        from config.settings import SETTINGS
        self.root = str(SETTINGS.data_dir / "tts_cache")

    def validate_absolute_path(self, root, absolute_path):
        if not absolute_path.startswith(root):
            raise tornado.web.HTTPError(403, reason="Forbidden")
        return absolute_path


class UserTTSHandler(UserJsonHandler):
    async def post(self):
        payload = self.json_body()
        text = str(payload.get("text", ""))
        voice = str(payload.get("voice", ""))
        if not 1 <= len(text) <= 5000:
            return self.write_json({"ok": False, "message": "文本长度需为 1—5000 个字符"}, 400)
        if not TTSService.is_enabled():
            return self.write_json({"ok": False, "message": "语音合成服务未启用"}, 400)
        try:
            result = await TTSService.synthesize(text, voice)
            TTSCallRepository.record(
                text_length=len(text),
                voice=voice,
                success=True,
                from_cache=result.get("from_cache", False),
            )
            return self.write_json(result)
        except TTSServiceError as exc:
            TTSCallRepository.record(
                text_length=len(text),
                voice=voice,
                success=False,
                error_message=str(exc),
            )
            return self.write_json({"ok": False, "message": str(exc)}, 500)