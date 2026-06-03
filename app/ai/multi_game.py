"""
멀티 모드 게임 로직 (Socket.IO 연동 전용).
- 두 플레이어 실시간 대결
- 먼저 표정을 성공한 플레이어에게 점수 부여
- 연속 3점(WIN_STREAK) 달성 시 무작위 패널티 부여
"""
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.ai.expression_analyzer import EXPRESSIONS, ExpressionAnalyzer
from app.ai.settings_loader import get, get_expression

PENALTIES = [
    "wink_left",     # 왼쪽 윙크
    "wink_right",    # 오른쪽 윙크
    "eyebrows_up",   # 눈썹 올리기
    "kiss",          # 뽀뽀
    "squint",        # 눈 찡긋
]


class RoomStatus(str, Enum):
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


@dataclass
class PlayerState:
    user_id: int
    socket_id: str
    score: int = 0
    streak: int = 0
    penalty: Optional[str] = None
    penalty_used: bool = False   # 게임당 패널티는 1회만
    round_start_at: Optional[float] = None
    last_match_at: float = 0.0  # 쿨다운용


@dataclass
class MultiRound:
    index: int
    expression: str
    winner_user_id: Optional[int] = None
    winner_elapsed_ms: Optional[int] = None
    started_at: float = field(default_factory=time.time)


@dataclass
class MultiRoomState:
    room_id: str
    players: dict[int, PlayerState]  # user_id -> PlayerState
    status: RoomStatus = RoomStatus.WAITING
    expressions: list[str] = field(default_factory=list)
    current_round: int = 0
    rounds: list[MultiRound] = field(default_factory=list)
    fail_shots: dict[int, list[str]] = field(default_factory=dict)     # user_id -> [b64]
    success_shots: dict[int, list[str]] = field(default_factory=dict)  # user_id -> [b64]
    created_at: float = field(default_factory=time.time)

    @property
    def current_expression(self) -> Optional[str]:
        if self.current_round >= len(self.expressions):
            return None
        return self.expressions[self.current_round]

    @property
    def is_finished(self) -> bool:
        return self.status == RoomStatus.FINISHED

    def get_scores(self) -> dict[int, int]:
        return {uid: p.score for uid, p in self.players.items()}


class MultiGameManager:
    def __init__(self):
        self._rooms: dict[str, MultiRoomState] = {}
        self._analyzer: Optional[ExpressionAnalyzer] = None

    def _get_analyzer(self) -> ExpressionAnalyzer:
        if self._analyzer is None:
            from app.ai.model_downloader import ensure_model
            model_path = ensure_model()
            self._analyzer = ExpressionAnalyzer.get_instance(model_path)
        return self._analyzer

    def create_room(self, room_id: str, player_a: tuple[int, str], player_b: tuple[int, str]) -> MultiRoomState:
        """room_id, (user_id, socket_id) 쌍 두 개로 방을 생성한다."""
        players = {
            player_a[0]: PlayerState(user_id=player_a[0], socket_id=player_a[1]),
            player_b[0]: PlayerState(user_id=player_b[0], socket_id=player_b[1]),
        }
        expressions = random.choices(EXPRESSIONS, k=get("multi", "max_rounds", 20))
        state = MultiRoomState(
            room_id=room_id,
            players=players,
            expressions=expressions,
            fail_shots={uid: [] for uid in players},
            success_shots={uid: [] for uid in players},
        )
        state.status = RoomStatus.IN_PROGRESS
        self._rooms[room_id] = state
        self._start_round(state)
        return state

    def get_room(self, room_id: str) -> Optional[MultiRoomState]:
        return self._rooms.get(room_id)

    def _start_round(self, state: MultiRoomState):
        now = time.time()
        for p in state.players.values():
            p.round_start_at = now
        round_obj = MultiRound(
            index=state.current_round,
            expression=state.current_expression,
        )
        state.rounds.append(round_obj)

    def process_frame(
        self,
        room_id: str,
        user_id: int,
        image_bytes: bytes,
    ) -> dict:
        """
        플레이어 프레임을 분석한다.
        먼저 threshold 초과 시 해당 플레이어 점수 +1, 다음 라운드 시작.
        이미 다른 플레이어가 이번 라운드를 이겼으면 무시.
        """
        state = self._rooms.get(room_id)
        if state is None:
            return {"error": "room_not_found"}
        if state.is_finished:
            return {"error": "game_finished"}
        if user_id not in state.players:
            return {"error": "player_not_in_room"}

        current_round_obj = state.rounds[-1] if state.rounds else None
        if current_round_obj and current_round_obj.winner_user_id is not None:
            # 이 라운드는 이미 끝남
            return {"status": "round_already_won", "winner": current_round_obj.winner_user_id}

        analyzer = self._get_analyzer()
        target = state.current_expression
        detected_expr, target_score = analyzer.match_score(target, image_bytes)

        player = state.players[user_id]

        if 0 < target_score < get("detection", "fail_shot_threshold", 0.30):
            import base64
            from app.ai.photo_storage import save_photo
            b64 = base64.b64encode(image_bytes).decode()
            if len(state.fail_shots[user_id]) < 4:
                round_idx = len(state.fail_shots[user_id])
                state.fail_shots[user_id].append(b64)
                save_photo(f"{state.room_id}_{user_id}", round_idx, image_bytes, "fail")

        now = time.time()
        expr_cfg = get_expression(target)
        cooldown_remaining = max(0.0, get("detection", "cooldown_sec", 1.0) - (now - player.last_match_at))
        matched = target_score >= expr_cfg["threshold"] and cooldown_remaining == 0.0
        payload: dict = {
            "room_id": room_id,
            "user_id": user_id,
            "target_expression": target,
            "detected_expression": detected_expr,
            "target_score": round(target_score, 4),
            "matched": matched,
            "cooldown_remaining": round(cooldown_remaining, 2),
            "round_index": state.current_round,
            "scores": state.get_scores(),
            "round_won": False,
            "penalty_assigned": None,
            "game_finished": False,
        }

        if matched:
            player.last_match_at = now
            elapsed = int((now - player.round_start_at) * 1000)
            current_round_obj.winner_user_id = user_id
            current_round_obj.winner_elapsed_ms = elapsed

            import base64 as _b64
            from app.ai.photo_storage import save_photo
            success_b64 = _b64.b64encode(image_bytes).decode()
            success_idx = len(state.success_shots[user_id])
            state.success_shots[user_id].append(success_b64)
            save_photo(f"{state.room_id}_{user_id}", success_idx, image_bytes, "success")

            player.score += 1
            player.streak += 1

            # 상대방 streak 초기화
            for uid, p in state.players.items():
                if uid != user_id:
                    p.streak = 0

            payload["round_won"] = True
            payload["winner_elapsed_ms"] = elapsed

            # 연속 승리 패널티 체크 — 게임당 1회만
            if player.streak >= get("multi", "win_streak_for_penalty", 3) and not player.penalty_used:
                penalty = random.choice(PENALTIES)
                player.penalty = penalty
                player.penalty_used = True
                player.streak = 0
                payload["penalty_assigned"] = {"user_id": user_id, "penalty": penalty}

            # 게임 종료 조건: 한 명이 10점 달성 또는 20라운드 소진
            max_score = max(p.score for p in state.players.values())
            if max_score >= get("multi", "max_score_to_win", 10) or state.current_round >= len(state.expressions) - 1:
                state.status = RoomStatus.FINISHED
                payload["game_finished"] = True
                payload["final_scores"] = state.get_scores()
                winner_id = max(state.players, key=lambda uid: state.players[uid].score)
                payload["winner_user_id"] = winner_id
            else:
                state.current_round += 1
                self._start_round(state)
                payload["next_expression"] = state.current_expression

            payload["scores"] = state.get_scores()

        return payload

    def apply_penalty_frame(
        self,
        room_id: str,
        user_id: int,
        image_bytes: bytes,
    ) -> dict:
        """패널티 표정 수행 여부를 검증한다. 패널티를 완료하면 penalty 해제."""
        state = self._rooms.get(room_id)
        if state is None:
            return {"error": "room_not_found"}

        player = state.players.get(user_id)
        if player is None or player.penalty is None:
            return {"penalty_active": False}

        analyzer = self._get_analyzer()
        penalty = player.penalty
        detected_expr, score = analyzer.match_score(penalty, image_bytes)

        threshold = get_expression(penalty).get("threshold", 0.6)
        cleared = score >= threshold
        if cleared:
            player.penalty = None

        return {
            "user_id": user_id,
            "penalty": penalty,
            "score": round(score, 4),
            "cleared": cleared,
        }

    def get_room_summary(self, room_id: str) -> Optional[dict]:
        state = self._rooms.get(room_id)
        if state is None:
            return None
        return {
            "room_id": room_id,
            "status": state.status,
            "scores": state.get_scores(),
            "rounds_played": state.current_round,
            "rounds": [
                {
                    "index": r.index,
                    "expression": r.expression,
                    "winner": r.winner_user_id,
                    "elapsed_ms": r.winner_elapsed_ms,
                }
                for r in state.rounds
            ],
        }

    def pop_fail_shots(self, room_id: str, user_id: int) -> list[str]:
        state = self._rooms.get(room_id)
        if state is None:
            return []
        shots = state.fail_shots.get(user_id, [])[:]
        state.fail_shots[user_id] = []
        return shots

    def pop_success_shots(self, room_id: str, user_id: int) -> list[str]:
        state = self._rooms.get(room_id)
        if state is None:
            return []
        shots = state.success_shots.get(user_id, [])[:]
        state.success_shots[user_id] = []
        return shots

    def cleanup(self, room_id: str):
        self._rooms.pop(room_id, None)


multi_manager = MultiGameManager()
