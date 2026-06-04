"""
멀티 모드 Socket.IO 이벤트 핸들러.

Client → Server events:
  join_room       { room_id, user_id }
  submit_frame    { room_id, user_id, image_base64 }
  penalty_frame   { room_id, user_id, image_base64 }
  leave_room      { room_id, user_id }

Server → Client events (broadcast to room):
  room_joined     { room_id, players }
  round_start     { round_index, expression, scores }
  frame_result    { user_id, target_score, matched, scores, ... }
  round_won       { winner_user_id, scores, next_expression | game_finished }
  penalty_update  { user_id, penalty, cleared }
  game_over       { winner_user_id, final_scores }
"""
import base64
import os

from flask_socketio import SocketIO, emit, join_room, leave_room

from app.ai.multi_game import multi_manager, RoomStatus
from app.ai.photo_composer import compose_from_game
from app.ai.photo_storage import get_fail_photo_urls
from app.ai.expression_analyzer import EXPRESSION_META
from app.models.db import db
from app.models.record import MultiRecord
from app.models.user import User


def _expr_info(key: str) -> dict:
    """표정 key → {key, label, emoji} dict"""
    meta = EXPRESSION_META.get(key, {})
    return {"key": key, "label": meta.get("label", key), "emoji": meta.get("emoji", "🎭")}

socketio = SocketIO()

# room_id -> {user_id: socket_id}
_pending_rooms: dict[str, dict] = {}


def init_socketio(app):
    socketio.init_app(
        app,
        cors_allowed_origins="*",
        async_mode="eventlet",
        logger=False,
        engineio_logger=False,
    )

    @app.after_request
    def add_private_network_header(response):
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response

    return socketio


@socketio.on("join_room")
def on_join_room(data):
    from flask import request as freq
    room_id = data["room_id"]
    user_id = int(data["user_id"])
    socket_id = freq.sid

    join_room(room_id)

    # 이미 진행 중인 방이면 현재 상태만 전달하고 종료
    existing = multi_manager.get_room(room_id)
    if existing and not existing.is_finished:
        existing.players[user_id].socket_id = socket_id
        emit("round_start", {
            "round_index": existing.current_round,
            "expression": _expr_info(existing.current_expression),
            "scores": existing.get_scores(),
            "total": len(existing.expressions),
        }, to=freq.sid)
        return

    if room_id not in _pending_rooms:
        _pending_rooms[room_id] = {}
    _pending_rooms[room_id][user_id] = socket_id

    players_in_room = _pending_rooms[room_id]
    emit("room_joined", {"room_id": room_id, "players": list(players_in_room.keys())}, to=room_id)

    # 두 명이 모이면 게임 시작
    if len(players_in_room) >= 2:
        player_ids = list(players_in_room.keys())
        pa = (player_ids[0], players_in_room[player_ids[0]])
        pb = (player_ids[1], players_in_room[player_ids[1]])
        state = multi_manager.create_room(room_id, pa, pb)
        del _pending_rooms[room_id]

        emit("round_start", {
            "round_index": state.current_round,
            "expression": _expr_info(state.current_expression),
            "scores": state.get_scores(),
            "total": len(state.expressions),
        }, to=room_id)


@socketio.on("submit_frame")
def on_submit_frame(data):
    room_id = data["room_id"]
    user_id = int(data["user_id"])
    b64 = data.get("image_base64", "")

    if "," in b64:
        b64 = b64.split(",", 1)[1]
    image_bytes = base64.b64decode(b64)

    # 전체 프레임(인생네컷용) — 없으면 채점용 이미지 사용
    photo_b64 = data.get("photo_base64", "")
    if "," in photo_b64:
        photo_b64 = photo_b64.split(",", 1)[1]
    photo_bytes = base64.b64decode(photo_b64) if photo_b64 else None

    result = multi_manager.process_frame(room_id, user_id, image_bytes, photo_bytes=photo_bytes)

    # 패널티 발생 시 닉네임 + 표정 정보 추가
    if result.get("penalty_assigned"):
        pa = result["penalty_assigned"]
        user = User.query.get(pa["user_id"])
        pa["username"] = user.username if user else str(pa["user_id"])
        pa.update(_expr_info(pa["penalty"]))   # key, label, emoji 추가

    # 프레임 분석 결과는 해당 유저에게만 전송
    from flask import request as freq
    emit("frame_result", result, to=freq.sid)

    if result.get("round_won"):
        winner_id = result["user_id"]
        winner = User.query.get(winner_id)
        next_expr_key = result.get("next_expression")
        emit("round_won", {
            "winner_user_id": winner_id,
            "winner_username": winner.username if winner else str(winner_id),
            "winner_elapsed_ms": result.get("winner_elapsed_ms"),
            "scores": result["scores"],
            "next_expression": _expr_info(next_expr_key) if next_expr_key else None,
            "game_finished": result.get("game_finished", False),
            "penalty_assigned": result.get("penalty_assigned"),
        }, to=room_id)

    if result.get("game_finished"):
        _save_multi_record(room_id, result)
        # video_url은 클라이언트가 game_over 후 upload-video → request_four_cut 으로 전달
        winner_id = result["winner_user_id"]
        winner = User.query.get(winner_id)
        emit("game_over", {
            "winner_user_id": winner_id,
            "winner_username": winner.username if winner else str(winner_id),
            "final_scores": result["final_scores"],
        }, to=room_id)


@socketio.on("penalty_frame")
def on_penalty_frame(data):
    room_id = data["room_id"]
    user_id = int(data["user_id"])
    b64 = data.get("image_base64", "")

    if "," in b64:
        b64 = b64.split(",", 1)[1]
    image_bytes = base64.b64decode(b64)

    result = multi_manager.apply_penalty_frame(room_id, user_id, image_bytes)
    emit("penalty_update", result, to=room_id)


_VIDEO_DIR = os.path.join("static", "videos")


def _save_video_b64(room_id: str, video_b64: str) -> str | None:
    """base64 영상 데이터를 파일로 저장하고 서버 URL을 반환한다."""
    try:
        os.makedirs(_VIDEO_DIR, exist_ok=True)
        if "," in video_b64:
            video_b64 = video_b64.split(",", 1)[1]
        video_bytes = base64.b64decode(video_b64)
        save_path = os.path.join(_VIDEO_DIR, f"{room_id}.webm")
        with open(save_path, "wb") as f:
            f.write(video_bytes)
        server_url = os.getenv("SERVER_URL", "http://localhost:5001")
        return f"{server_url}/api/share/video/{room_id}"
    except Exception:
        return None


@socketio.on("request_four_cut")
def on_request_four_cut(data):
    """
    game_over 후 클라이언트가 호출.
    { room_id, user_id, video_url?, video_base64? }
    - video_base64 전달 시 서버에서 영상을 직접 저장 (별도 HTTP 업로드 불필요)
    - video_url 전달 시 기존 방식 유지
    → life_four_cut 이벤트를 해당 클라이언트에게만 전송.
    """
    from flask import request as freq
    room_id    = data["room_id"]
    user_id    = int(data["user_id"])
    video_url  = data.get("video_url") or None
    video_b64  = data.get("video_base64") or None

    # 클라이언트가 영상 데이터를 직접 보낸 경우 → 서버에서 저장
    if video_b64 and not video_url:
        video_url = _save_video_b64(room_id, video_b64)

    state = multi_manager.get_room(room_id)
    if state is None:
        return

    shots = multi_manager.pop_fail_shots(room_id, user_id)
    multi_manager.pop_success_shots(room_id, user_id)

    user_obj  = User.query.get(user_id)
    user_name = user_obj.username if user_obj else ""

    b64       = compose_from_game(shots, user_name=user_name, video_url=video_url)
    fail_urls = get_fail_photo_urls(f"{room_id}_{user_id}")

    emit("life_four_cut", {
        "user_id":         user_id,
        "image":           b64,
        "fail_photo_urls": fail_urls,
        "video_url":       video_url,
    }, to=freq.sid)

    # 두 플레이어 모두 요청 완료 시 방 정리
    if not any(multi_manager.pop_fail_shots(room_id, uid) for uid in state.players if uid != user_id):
        multi_manager.cleanup(room_id)


@socketio.on("leave_room")
def on_leave_room(data):
    room_id = data["room_id"]
    leave_room(room_id)
    if room_id in _pending_rooms:
        uid = int(data.get("user_id", 0))
        _pending_rooms[room_id].pop(uid, None)


def _save_multi_record(room_id: str, result: dict):
    state = multi_manager.get_room(room_id)
    if state is None:
        return
    player_ids = list(state.players.keys())
    scores = state.get_scores()
    record = MultiRecord(
        room_id=room_id,
        winner_user_id=result.get("winner_user_id"),
        player_a_id=player_ids[0],
        player_b_id=player_ids[1],
        score_a=scores.get(player_ids[0], 0),
        score_b=scores.get(player_ids[1], 0),
        rounds_played=state.current_round,
    )
    db.session.add(record)
    db.session.commit()


def _emit_life_four_cuts(room_id: str):
    state = multi_manager.get_room(room_id)
    if state is None:
        return
    for user_id, player in state.players.items():
        shots = multi_manager.pop_fail_shots(room_id, user_id)
        multi_manager.pop_success_shots(room_id, user_id)  # 메모리 정리 (파일은 저장됨)

        user_obj = User.query.get(user_id)
        user_name = user_obj.username if user_obj else ""

        b64 = compose_from_game(shots, user_name=user_name)
        fail_urls = get_fail_photo_urls(f"{room_id}_{user_id}")

        # 각 플레이어에게 자신의 인생네컷만 개별 전송
        emit("life_four_cut", {
            "user_id": user_id,
            "image": b64,
            "fail_photo_urls": fail_urls,
        }, to=player.socket_id)
