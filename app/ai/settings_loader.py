"""
game_settings.json 로더.
get() 으로 어디서든 설정값을 꺼내 쓰고,
reload() 로 서버 재시작 없이 파일을 다시 읽는다.
"""
import json
import threading
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent / "game_settings.json"

_lock = threading.Lock()
_settings: dict = {}


def _load() -> dict:
    raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    # _comment 키 제거
    def strip(obj):
        if isinstance(obj, dict):
            return {k: strip(v) for k, v in obj.items() if k != "_comment"}
        return obj
    return strip(raw)


def reload():
    global _settings
    with _lock:
        _settings = _load()


def get(section: str, key: str, default=None):
    """get('detection', 'match_threshold') 형태로 사용."""
    return _settings.get(section, {}).get(key, default)


def get_expression(name: str) -> dict:
    """
    표정별 오버라이드 설정을 반환한다.
    없으면 detection 기본값으로 채워서 반환.
    """
    base = {
        "threshold": get("detection", "match_threshold", 0.70),
        "amplify":   get("detection", "amplify", 1.5),
    }
    override = _settings.get("expression_weights", {}).get(name, {})
    return {**base, **override}


def all_settings() -> dict:
    return dict(_settings)


# 모듈 임포트 시 1회 로드
reload()
