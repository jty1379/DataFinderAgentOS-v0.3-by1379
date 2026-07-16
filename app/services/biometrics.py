"""人脸活体校验与 MediaPipe 多帧手势识别。"""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import threading
from collections import Counter
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np


class BiometricError(ValueError):
    """可安全展示给用户的生物识别错误。"""


def decode_frames(raw_frames: list[str], *, minimum: int = 3, maximum: int = 8) -> list[np.ndarray]:
    if not isinstance(raw_frames, list) or not minimum <= len(raw_frames) <= maximum:
        raise BiometricError(f"请连续采集 {minimum}—{maximum} 帧画面")
    decoded: list[np.ndarray] = []
    for raw in raw_frames:
        if not isinstance(raw, str) or "," not in raw:
            raise BiometricError("摄像头画面格式不正确")
        encoded = raw.split(",", 1)[1]
        if len(encoded) > 2_000_000:
            raise BiometricError("单帧画面过大")
        try:
            buffer = np.frombuffer(base64.b64decode(encoded, validate=True), dtype=np.uint8)
            image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        except (ValueError, cv2.error) as exc:
            raise BiometricError("无法解析摄像头画面") from exc
        if image is None or image.shape[0] < 120 or image.shape[1] < 120:
            raise BiometricError("摄像头画面尺寸过小")
        decoded.append(image)
    return decoded


class FaceVerifier:
    _cascade = None
    _cascade_lock = threading.Lock()

    @classmethod
    def _classifier(cls):
        """从 ASCII 临时路径加载模型，规避 OpenCV Windows 中文路径缺陷。"""
        with cls._cascade_lock:
            if cls._cascade is not None and not cls._cascade.empty():
                return cls._cascade
            source = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
            try:
                content = source.read_bytes()
                digest = hashlib.sha256(content).hexdigest()[:12]
                runtime_dir = Path(tempfile.gettempdir()) / "datafinderagentos_models"
                runtime_dir.mkdir(parents=True, exist_ok=True)
                runtime_model = runtime_dir / f"face-{digest}.xml"
                if not runtime_model.exists() or runtime_model.stat().st_size != len(content):
                    runtime_model.write_bytes(content)
                classifier = cv2.CascadeClassifier(str(runtime_model))
            except (OSError, cv2.error) as exc:
                raise BiometricError("人脸检测模型加载失败，请检查 OpenCV 安装") from exc
            if classifier.empty():
                raise BiometricError("人脸检测模型不可用，请重新安装项目依赖")
            cls._cascade = classifier
            return classifier

    @classmethod
    def _face_feature(cls, image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        try:
            faces = cls._classifier().detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(72, 72)
            )
        except cv2.error as exc:
            raise BiometricError("人脸检测暂时不可用，请重新启动服务后重试") from exc
        if len(faces) != 1:
            message = "未检测到清晰人脸" if len(faces) == 0 else "画面中只能出现一张人脸"
            raise BiometricError(message)
        x, y, width, height = max(faces, key=lambda item: item[2] * item[3])
        margin = int(min(width, height) * 0.08)
        crop = gray[max(0, y - margin) : min(gray.shape[0], y + height + margin),
                    max(0, x - margin) : min(gray.shape[1], x + width + margin)]
        normalized = cv2.resize(crop, (96, 96), interpolation=cv2.INTER_AREA)
        normalized = cv2.equalizeHist(normalized)
        focus = cv2.Laplacian(normalized, cv2.CV_64F).var()
        if focus < 35:
            raise BiometricError("人脸画面较模糊，请保持稳定并增加光线")
        reduced = cv2.resize(normalized, (64, 64)).astype(np.float32) / 255.0
        feature = cv2.dct(reduced)[:16, :16].flatten()[1:]
        feature = feature / max(float(np.linalg.norm(feature)), 1e-6)
        return feature, normalized

    @classmethod
    def extract_profile(cls, frames: list[np.ndarray]) -> tuple[list[float], dict]:
        features: list[np.ndarray] = []
        faces: list[np.ndarray] = []
        for frame in frames:
            feature, face = cls._face_feature(frame)
            features.append(feature)
            faces.append(face)
        motion = float(np.mean([
            np.mean(cv2.absdiff(faces[index - 1], faces[index])) / 255.0
            for index in range(1, len(faces))
        ]))
        if motion < 0.012:
            raise BiometricError("活体变化不足，请轻微转头或眨眼后重试")
        if motion > 0.35:
            raise BiometricError("画面变化过大，请保持脸部位于取景框内")
        mean = np.mean(features, axis=0)
        mean /= max(float(np.linalg.norm(mean)), 1e-6)
        consistency = float(np.mean([np.dot(mean, feature) for feature in features]))
        if consistency < 0.70:
            raise BiometricError("多帧人脸不一致，请由同一用户重新采集")
        return [round(float(value), 8) for value in mean], {
            "motion": round(motion, 4),
            "consistency": round(consistency, 4),
            "samples": len(frames),
        }

    @staticmethod
    def compare(stored: list[float], candidate: list[float]) -> float:
        first = np.asarray(stored, dtype=np.float32)
        second = np.asarray(candidate, dtype=np.float32)
        if first.shape != second.shape or first.size < 32:
            return 0.0
        return float(np.dot(first, second) / max(np.linalg.norm(first) * np.linalg.norm(second), 1e-6))


class GestureRecognizer:
    MODEL_PATH = Path(__file__).resolve().parent / "models" / "gesture_recognizer.task"
    LABELS = {"Victory": "victory", "Closed_Fist": "fist", "Open_Palm": "open_palm"}
    _lock = threading.Lock()
    _recognizer = None

    @classmethod
    def _instance(cls):
        with cls._lock:
            if cls._recognizer is None:
                options = mp.tasks.vision.GestureRecognizerOptions(
                    # C++ 文件加载器在 Windows 中文路径下失败，直接传入本地模型字节。
                    base_options=mp.tasks.BaseOptions(model_asset_buffer=cls.MODEL_PATH.read_bytes()),
                    running_mode=mp.tasks.vision.RunningMode.IMAGE,
                    num_hands=1,
                    min_hand_detection_confidence=0.55,
                    min_hand_presence_confidence=0.55,
                )
                cls._recognizer = mp.tasks.vision.GestureRecognizer.create_from_options(options)
        return cls._recognizer

    @classmethod
    def recognize(cls, frames: list[np.ndarray]) -> dict:
        predictions: list[tuple[str, float]] = []
        recognizer = cls._instance()
        for frame in frames:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = recognizer.recognize(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            if not result.gestures or not result.gestures[0]:
                continue
            category = result.gestures[0][0]
            label = cls.LABELS.get(category.category_name)
            if label and category.score >= 0.55:
                predictions.append((label, float(category.score)))
        if not predictions:
            raise BiometricError("未识别到胜利、握拳或张开手掌手势")
        winner, votes = Counter(item[0] for item in predictions).most_common(1)[0]
        required = max(2, len(frames) // 2 + 1)
        if votes < required:
            raise BiometricError("多帧手势不一致，请保持手势一秒后重试")
        confidence = sum(score for label, score in predictions if label == winner) / votes
        return {"gesture": winner, "confidence": round(confidence, 4), "votes": votes}


def dumps_embedding(values: list[float]) -> str:
    return json.dumps(values, separators=(",", ":"))


def loads_embedding(value: str) -> list[float]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise BiometricError("人脸档案已损坏，请重新录入") from exc
    if not isinstance(parsed, list):
        raise BiometricError("人脸档案已损坏，请重新录入")
    return [float(item) for item in parsed]
