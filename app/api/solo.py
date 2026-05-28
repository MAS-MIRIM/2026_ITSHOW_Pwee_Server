"""
솔로 모드 REST API.

POST /api/solo/start          게임 세션 생성
POST /api/solo/frame          프레임 분석 및 표정 매칭
GET  /api/solo/summary/<id>   최종 결과 조회
POST /api/solo/finish         결과 DB 저장 + 망한샷 반환
"""
import base64
import uuid

from flask import Blueprint, jsonify, request

from app.ai.expression_analyzer import EXPRESSION_META
from app.ai.solo_game import solo_manager
from app.ai.photo_composer import compose_from_game
from app.models.db import db
from app.models.record import SoloRecord

solo_bp = Blueprint("solo", __name__, url_prefix="/api/solo")


def _expr_info(name: str) -> dict:
    """표정 key에 대한 label/emoji 포함 dict 반환."""
    meta = EXPRESSION_META.get(name, {})
    return {
        "key": name,
        "label": meta.get("label", name),
        "emoji": meta.get("emoji", "🎭"),
    }


@solo_bp.post("/start")
def start_game():
    data = request.get_json(force=True)
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id가 필요합니다."}), 400

    game_id = str(uuid.uuid4())
    state = solo_manager.create_game(game_id, user_id)
    return jsonify({
        "game_id": game_id,
        "expressions": [_expr_info(e) for e in state.expressions],
        "first_expression": _expr_info(state.current_expression),
        "total": len(state.expressions),
    }), 201


@solo_bp.post("/frame")
def process_frame():
    """
    JSON body: { game_id, image_base64 }
    또는 multipart/form-data: game_id + file
    """
    if request.content_type and "multipart" in request.content_type:
        game_id = request.form.get("game_id")
        img_file = request.files.get("image")
        if not game_id or not img_file:
            return jsonify({"error": "game_id와 image가 필요합니다."}), 400
        image_bytes = img_file.read()
    else:
        data = request.get_json(force=True)
        game_id = data.get("game_id")
        b64 = data.get("image_base64", "")
        if not game_id or not b64:
            return jsonify({"error": "game_id와 image_base64가 필요합니다."}), 400
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        image_bytes = base64.b64decode(b64)

    result = solo_manager.process_frame(game_id, image_bytes)

    if "error" in result:
        error_messages = {
            "game_not_found": "게임 세션을 찾을 수 없습니다.",
            "game_already_finished": "이미 종료된 게임입니다.",
        }
        return jsonify({"error": error_messages.get(result["error"], result["error"])}), 404

    # 표정 key에 label/emoji 보강
    for field_name in ("target_expression", "detected_expression", "next_expression"):
        if field_name in result and result[field_name]:
            result[field_name] = _expr_info(result[field_name])

    if "round_results" in result:
        for r in result["round_results"]:
            r["expression"] = _expr_info(r["expression"])

    return jsonify(result)


@solo_bp.get("/summary/<game_id>")
def get_summary(game_id: str):
    summary = solo_manager.get_summary(game_id)
    if summary is None:
        return jsonify({"error": "게임 세션을 찾을 수 없거나 아직 종료되지 않았습니다."}), 404

    summary["expressions"] = [_expr_info(e) for e in summary["expressions"]]
    for r in summary.get("round_results", []):
        r["expression"] = _expr_info(r["expression"])

    return jsonify(summary)


@solo_bp.post("/finish")
def finish_game():
    """
    게임 종료 후 DB 저장 + 인생네컷 생성.
    JSON body: { game_id, user_name? }
    """
    data = request.get_json(force=True)
    game_id = data.get("game_id")
    if not game_id:
        return jsonify({"error": "game_id가 필요합니다."}), 400
    user_name = data.get("user_name", "")

    summary = solo_manager.get_summary(game_id)
    if summary is None:
        return jsonify({"error": "게임 세션을 찾을 수 없거나 아직 종료되지 않았습니다."}), 404

    record = SoloRecord(
        user_id=summary["user_id"],
        clear_time_ms=summary["clear_time_ms"],
        expression_count=len(summary["expressions"]),
    )
    db.session.add(record)
    db.session.commit()

    fail_shots = solo_manager.pop_fail_shots(game_id)
    life_four_cut_b64 = compose_from_game(
        fail_shots,
        user_name=user_name,
        clear_time_ms=summary["clear_time_ms"],
    )

    solo_manager.cleanup(game_id)

    return jsonify({
        "record_id": record.id,
        "clear_time_ms": summary["clear_time_ms"],
        "life_four_cut": life_four_cut_b64,
        "fail_shot_count": len(fail_shots),
    })
