"""
MediaPipe Face Landmarker 기반 표정 분석기.
표정 정의는 app/ai/expressions/*.json 에서 로드한다.
"""
import base64
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

from app.ai.settings_loader import get_expression

EXPRESSIONS_DIR = Path(__file__).parent / "expressions"


def _load_expressions() -> tuple[list[str], dict, dict, dict]:
    """
    expressions/ 디렉터리의 JSON 파일을 모두 읽어
    (names, rules, suppress_map, meta) 를 반환한다.

    JSON 스키마:
      label   : str   — 한국어 이름 (UI 표시용)
      emoji   : str   — 이모지
      keys    : list  — 점수 계산에 쓸 blend shape 이름 목록 (max 방식)
      suppress: str|null — 이 blend shape 값이 높으면 점수를 깎음 (윙크 반대눈 등)
    """
    names: list[str] = []
    rules: dict[str, list[str]] = {}
    suppress_map: dict[str, str] = {}
    meta: dict[str, dict] = {}

    for path in sorted(EXPRESSIONS_DIR.glob("*.json")):
        name = path.stem
        data = json.loads(path.read_text(encoding="utf-8"))
        names.append(name)
        rules[name] = data.get("keys", [])
        if data.get("suppress"):
            suppress_map[name] = data["suppress"]
        meta[name] = {"label": data.get("label", name), "emoji": data.get("emoji", "🎭")}

    return names, rules, suppress_map, meta


# 모듈 로드 시 1회만 읽음 — 서버 재시작 없이 바꾸려면 reload_expressions() 호출
EXPRESSIONS, EXPRESSION_RULES, SUPPRESS_MAP, EXPRESSION_META = _load_expressions()


def reload_expressions():
    """런타임에 JSON을 다시 읽어 전역 변수를 갱신한다."""
    global EXPRESSIONS, EXPRESSION_RULES, SUPPRESS_MAP, EXPRESSION_META
    EXPRESSIONS, EXPRESSION_RULES, SUPPRESS_MAP, EXPRESSION_META = _load_expressions()


@dataclass
class ExpressionResult:
    expression: str
    score: float
    all_scores: dict[str, float] = field(default_factory=dict)
    landmarks_detected: bool = True


class ExpressionAnalyzer:
    _instance: Optional["ExpressionAnalyzer"] = None
    _lock = threading.Lock()

    def __init__(self, model_path: str = "app/ai/models/face_landmarker.task"):
        base_options = mp_python.BaseOptions(model_asset_path=model_path)
        options = mp_vision.FaceLandmarkerOptions(
            base_options=base_options,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=False,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmarker = mp_vision.FaceLandmarker.create_from_options(options)

    @classmethod
    def get_instance(cls, model_path: str = "app/ai/models/face_landmarker.task") -> "ExpressionAnalyzer":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(model_path)
        return cls._instance

    def analyze_frame(self, image_bytes: bytes) -> ExpressionResult:
        nparr = np.frombuffer(image_bytes, np.uint8)
        bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if bgr is None:
            return ExpressionResult("unknown", 0.0, {}, landmarks_detected=False)

        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect(mp_image)

        if not result.face_blendshapes:
            return ExpressionResult("unknown", 0.0, {}, landmarks_detected=False)

        blend_map = {bs.category_name: bs.score for bs in result.face_blendshapes[0]}
        return self._score_expressions(blend_map)

    def analyze_base64(self, b64_string: str) -> ExpressionResult:
        if "," in b64_string:
            b64_string = b64_string.split(",", 1)[1]
        return self.analyze_frame(base64.b64decode(b64_string))

    def _score_expressions(self, blend_map: dict[str, float]) -> ExpressionResult:
        all_scores: dict[str, float] = {}

        for expr, keys in EXPRESSION_RULES.items():
            if not keys:
                all_scores[expr] = 0.0
                continue

            raw = max(blend_map.get(k, 0.0) for k in keys)

            if expr in SUPPRESS_MAP:
                penalty = blend_map.get(SUPPRESS_MAP[expr], 0.0)
                raw = max(0.0, raw - penalty * 0.8)

            # 표정별 감도 증폭 (game_settings.json의 expression_weights[expr].amplify)
            amplify = get_expression(expr)["amplify"]
            raw = min(raw * amplify, 1.0)
            all_scores[expr] = float(np.clip(raw, 0.0, 1.0))

        # neutral: 다른 표정이 모두 낮을수록 높음
        non_neutral_max = max((v for k, v in all_scores.items() if k != "neutral"), default=0.0)
        all_scores["neutral"] = float(np.clip(1.0 - non_neutral_max, 0.0, 1.0))

        best_expr = max(all_scores, key=lambda k: all_scores[k])
        return ExpressionResult(
            expression=best_expr,
            score=all_scores[best_expr],
            all_scores=all_scores,
            landmarks_detected=True,
        )

    def match_score(self, target_expression: str, image_bytes: bytes) -> tuple[str, float]:
        result = self.analyze_frame(image_bytes)
        if not result.landmarks_detected:
            return ("unknown", 0.0)
        return (result.expression, result.all_scores.get(target_expression, 0.0))
