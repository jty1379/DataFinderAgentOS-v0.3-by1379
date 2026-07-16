"""人脸档案、手势冷却和全局开关 Repository。"""

from __future__ import annotations

from app.models.db import connection_scope


class BiometricRepository:
    @staticmethod
    def face_login_enabled() -> bool:
        with connection_scope() as connection:
            row = connection.execute(
                "SELECT value FROM system_settings WHERE key='face_login_enabled'"
            ).fetchone()
        return row is not None and row["value"] == "1"

    @staticmethod
    def set_face_login_enabled(enabled: bool, actor_id: int) -> None:
        with connection_scope() as connection:
            connection.execute(
                """INSERT INTO system_settings(key,value,updated_by,updated_at)
                   VALUES ('face_login_enabled',?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                   updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP""",
                ("1" if enabled else "0", actor_id),
            )
            connection.commit()

    @staticmethod
    def face_profile(user_id: int) -> dict | None:
        with connection_scope() as connection:
            row = connection.execute(
                "SELECT * FROM face_profiles WHERE user_id=?", (int(user_id),)
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def save_face_profile(user_id: int, embedding: str, samples: int) -> None:
        with connection_scope() as connection:
            connection.execute(
                """INSERT INTO face_profiles(user_id,embedding,sample_count,enabled)
                   VALUES (?,?,?,1)
                   ON CONFLICT(user_id) DO UPDATE SET embedding=excluded.embedding,
                   sample_count=excluded.sample_count,enabled=1,updated_at=CURRENT_TIMESTAMP""",
                (int(user_id), embedding, int(samples)),
            )
            connection.commit()

    @staticmethod
    def delete_face_profile(user_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute("DELETE FROM face_profiles WHERE user_id=?", (int(user_id),))
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def toggle_user_face(user_id: int, enabled: bool) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                "UPDATE face_profiles SET enabled=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
                (1 if enabled else 0, int(user_id)),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def log_gesture(user_id: int, gesture: str, action: str, confidence: float) -> bool:
        with connection_scope() as connection:
            recent = connection.execute(
                """SELECT 1 FROM gesture_events WHERE user_id=? AND gesture=?
                   AND datetime(triggered_at) > datetime('now','-5 seconds') LIMIT 1""",
                (int(user_id), gesture),
            ).fetchone()
            if recent:
                return False
            connection.execute(
                "INSERT INTO gesture_events(user_id,gesture,action,confidence) VALUES (?,?,?,?)",
                (int(user_id), gesture, action, float(confidence)),
            )
            connection.commit()
        return True
