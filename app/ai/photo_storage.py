"""
게임 중 촬영된 성공/실패 사진을 static/photos/<game_id>/ 에 파일로 저장한다.

디렉토리 구조:
  static/photos/<game_id>/success_<round>.jpg   — 표정 성공 순간 프레임
  static/photos/<game_id>/fail_<round>.jpg       — 표정 실패(망한샷) 프레임
"""
import base64
import io
import os

from PIL import Image

PHOTO_BASE = os.path.join("static", "photos")


def _game_dir(game_id: str) -> str:
    path = os.path.join(PHOTO_BASE, game_id)
    os.makedirs(path, exist_ok=True)
    return path


def save_photo(game_id: str, round_index: int, image_bytes: bytes, kind: str) -> str:
    """
    kind: "success" | "fail"
    Returns: 저장된 파일의 URL 경로 (예: /static/photos/<game_id>/fail_0.jpg)
    """
    directory = _game_dir(game_id)
    filename = f"{kind}_{round_index}.jpg"
    filepath = os.path.join(directory, filename)

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img.save(filepath, format="JPEG", quality=85)
    except Exception:
        return ""

    return f"/static/photos/{game_id}/{filename}"


def save_photo_b64(game_id: str, round_index: int, b64: str, kind: str) -> str:
    """base64 문자열을 받아 저장한다."""
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    try:
        image_bytes = base64.b64decode(b64)
    except Exception:
        return ""
    return save_photo(game_id, round_index, image_bytes, kind)


def get_fail_photo_urls(game_id: str) -> list[str]:
    """저장된 fail_*.jpg URL 목록을 라운드 순서대로 반환한다."""
    directory = os.path.join(PHOTO_BASE, game_id)
    if not os.path.isdir(directory):
        return []
    files = sorted(
        (f for f in os.listdir(directory) if f.startswith("fail_") and f.endswith(".jpg")),
        key=lambda f: int(f.split("_")[1].split(".")[0]),
    )
    return [f"/static/photos/{game_id}/{f}" for f in files]
