"""
단일 프레임 표정 분석 API

POST /api/analyze   { image_base64 } → 표정 분석 결과 전체 반환
"""
import base64

from flask import Blueprint, jsonify, request

from app.ai.expression_analyzer import ExpressionAnalyzer
from app.ai.model_downloader import ensure_model

analyze_bp = Blueprint("analyze", __name__, url_prefix="/api/analyze")

_analyzer = None


def _get_analyzer() -> ExpressionAnalyzer:
    global _analyzer
    if _analyzer is None:
        model_path = ensure_model()
        _analyzer = ExpressionAnalyzer.get_instance(model_path)
    return _analyzer


@analyze_bp.post("")
def analyze():
    if request.content_type and "multipart" in request.content_type:
        img_file = request.files.get("image")
        if not img_file:
            return jsonify({"error": "image 파일이 필요합니다."}), 400
        image_bytes = img_file.read()
    else:
        data = request.get_json(force=True)
        b64 = data.get("image_base64", "")
        if not b64:
            return jsonify({"error": "image_base64가 필요합니다."}), 400
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        image_bytes = base64.b64decode(b64)

    analyzer = _get_analyzer()
    result = analyzer.analyze_frame(image_bytes)

    return jsonify({
        "expression": result.expression,
        "score": round(result.score, 4),
        "all_scores": {k: round(v, 4) for k, v in result.all_scores.items()},
        "landmarks_detected": result.landmarks_detected,
    })
