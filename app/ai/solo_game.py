"""
솔로 모드 게임 로직.
- 10개 랜덤 표정 시퀀스 생성
- 프레임별 일치도 판정
- 클리어 시간 계산
"""
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from app.ai.expression_analyzer import EXPRESSIONS, ExpressionAnalyzer
from app.ai.settings_loader import get, get_expression


@dataclass
class SoloRoundResult:
    expression: str
    achieved: bool
    score: float
    elapsed_ms: int


@dataclass
class SoloGameState:
    game_id: str
    user_id: int
    expressions: list[str]
    current_index: int = 0
    round_results: list[SoloRoundResult] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    fail_shots: dict[int, str] = field(default_factory=dict)  # round_index → base64
    last_match_at: float = 0.0  # 직전 성공 시각 — 쿨다운용
    round_started_at: float = field(default_factory=time.time)  # 현재 라운드 시작 시각

    @property
    def is_finished(self) -> bool:
        return self.current_index >= len(self.expressions)

    @property
    def clear_time_ms(self) -> Optional[int]:
        if self.finished_at is None:
            return None
        return int((self.finished_at - self.started_at) * 1000)

    @property
    def current_expression(self) -> Optional[str]:
        if self.is_finished:
            return None
        return self.expressions[self.current_index]


class SoloGameManager:
    def __init__(self):
        self._sessions: dict[str, SoloGameState] = {}
        self._analyzer = None

    def _get_analyzer(self) -> ExpressionAnalyzer:
        if self._analyzer is None:
            from app.ai.model_downloader import ensure_model
            model_path = ensure_model()
            self._analyzer = ExpressionAnalyzer.get_instance(model_path)
        return self._analyzer

    def create_game(self, game_id: str, user_id: int) -> SoloGameState:
        expressions = random.sample(EXPRESSIONS, get("solo", "expression_count", 10))
        state = SoloGameState(
            game_id=game_id,
            user_id=user_id,
            expressions=expressions,
        )
        self._sessions[game_id] = state
        return state

    def get_game(self, game_id: str) -> Optional[SoloGameState]:
        return self._sessions.get(game_id)

    def process_frame(
        self,
        game_id: str,
        image_bytes: bytes,
    ) -> dict:
        """
        프레임 이미지를 분석해 현재 표정 매칭 결과를 반환한다.
        threshold 초과 시 자동으로 다음 표정으로 넘어간다.
        """
        state = self._sessions.get(game_id)
        if state is None:
            return {"error": "game_not_found"}  # API 레이어에서 한국어로 변환됨
        if state.is_finished:
            return {"error": "game_already_finished"}  # API 레이어에서 한국어로 변환됨

        analyzer = self._get_analyzer()
        target = state.current_expression
        detected_expr, target_score = analyzer.match_score(target, image_bytes)

        idx = state.current_index
        if 0 < target_score < get("detection", "fail_shot_threshold", 0.30) and idx not in state.fail_shots:
            import base64
            state.fail_shots[idx] = base64.b64encode(image_bytes).decode()

        now = time.time()
        round_time_limit = get("solo", "round_time_limit_sec", 15.0)
        round_elapsed = now - state.round_started_at
        timed_out = round_elapsed >= round_time_limit

        expr_cfg = get_expression(target)
        cooldown_remaining = max(0.0, get("detection", "cooldown_sec", 1.0) - (now - state.last_match_at))
        matched = target_score >= expr_cfg["threshold"] and cooldown_remaining == 0.0

        result_payload = {
            "game_id": game_id,
            "target_expression": target,
            "detected_expression": detected_expr,
            "target_score": round(target_score, 4),
            "matched": matched,
            "timed_out": timed_out,
            "round_time_remaining": round(max(0.0, round_time_limit - round_elapsed), 2),
            "cooldown_remaining": round(cooldown_remaining, 2),
            "current_index": state.current_index,
            "total": len(state.expressions),
            "finished": False,
        }

        def _advance_round(achieved: bool, score: float):
            elapsed = int((now - state.started_at) * 1000)
            state.round_results.append(
                SoloRoundResult(
                    expression=target,
                    achieved=achieved,
                    score=score,
                    elapsed_ms=elapsed,
                )
            )
            state.current_index += 1
            state.round_started_at = now

            if state.is_finished:
                state.finished_at = time.time()
                result_payload["finished"] = True
                result_payload["clear_time_ms"] = state.clear_time_ms
                result_payload["round_results"] = [
                    {
                        "expression": r.expression,
                        "score": round(r.score, 4),
                        "elapsed_ms": r.elapsed_ms,
                        "achieved": r.achieved,
                    }
                    for r in state.round_results
                ]
            else:
                result_payload["next_expression"] = state.current_expression

        if matched:
            state.last_match_at = now
            _advance_round(achieved=True, score=target_score)
        elif timed_out:
            # 타임아웃 — 망한샷 없으면 현재 프레임으로 저장
            if idx not in state.fail_shots:
                import base64 as _b64
                state.fail_shots[idx] = _b64.b64encode(image_bytes).decode()
            _advance_round(achieved=False, score=target_score)

        return result_payload

    def get_summary(self, game_id: str) -> Optional[dict]:
        state = self._sessions.get(game_id)
        if state is None or not state.is_finished:
            return None
        return {
            "game_id": game_id,
            "user_id": state.user_id,
            "clear_time_ms": state.clear_time_ms,
            "expressions": state.expressions,
            "round_results": [
                {"expression": r.expression, "score": round(r.score, 4), "elapsed_ms": r.elapsed_ms}
                for r in state.round_results
            ],
            "fail_shot_count": len(state.fail_shots),
        }

    def pop_fail_shots(self, game_id: str) -> list[str]:
        """망한샷 base64 리스트를 라운드 순서대로 꺼내고 세션에서 제거한다."""
        state = self._sessions.get(game_id)
        if state is None:
            return []
        shots = [state.fail_shots[i] for i in sorted(state.fail_shots)]
        state.fail_shots.clear()
        return shots

    def cleanup(self, game_id: str):
        self._sessions.pop(game_id, None)


# 앱 전역 싱글톤
solo_manager = SoloGameManager()
