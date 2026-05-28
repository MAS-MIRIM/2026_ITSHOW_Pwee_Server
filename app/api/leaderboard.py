"""
리더보드 API.

GET /api/leaderboard/solo?limit=20    솔로 클리어 타임 TOP N
"""
from flask import Blueprint, jsonify, request

from app.models.record import SoloRecord

leaderboard_bp = Blueprint("leaderboard", __name__, url_prefix="/api/leaderboard")


@leaderboard_bp.get("/solo")
def solo_leaderboard():
    try:
        limit = min(int(request.args.get("limit", 20)), 100)
    except ValueError:
        return jsonify({"error": "limit은 정수여야 합니다."}), 400

    records = (
        SoloRecord.query
        .order_by(SoloRecord.clear_time_ms.asc())
        .limit(limit)
        .all()
    )
    return jsonify({
        "leaderboard": [r.to_dict() for r in records],
        "count": len(records),
    })
