"""
망한샷 + 인생네컷 합성 모듈.
- base64 이미지 최대 4장을 2x2 그리드로 합성
- 프레임 이미지(assets/frame.png)를 오버레이
- 결과를 base64 JPEG으로 반환
"""
import base64
import io
import os
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FRAME_PATH = "app/ai/assets/frame.png"
CELL_W, CELL_H = 320, 240
GRID_COLS, GRID_ROWS = 2, 2
CANVAS_W = CELL_W * GRID_COLS
CANVAS_H = CELL_H * GRID_ROWS

# 각 셀 좌상단 좌표
CELL_POSITIONS = [
    (0, 0), (CELL_W, 0),
    (0, CELL_H), (CELL_W, CELL_H),
]


def _decode_b64_image(b64: str) -> Optional[Image.Image]:
    try:
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        data = base64.b64decode(b64)
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None


def _placeholder(width: int, height: int, index: int) -> Image.Image:
    img = Image.new("RGB", (width, height), color=(30, 30, 30))
    draw = ImageDraw.Draw(img)
    draw.text(
        (width // 2 - 10, height // 2 - 10),
        f"#{index + 1}",
        fill=(180, 180, 180),
    )
    return img


def compose_life_four_cut(
    fail_shots: list[str],
    frame_path: str = FRAME_PATH,
) -> str:
    """
    fail_shots: base64 이미지 리스트 (최대 4개)
    Returns: base64 JPEG 문자열
    """
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), color=(20, 20, 20))

    for i, (x, y) in enumerate(CELL_POSITIONS):
        if i < len(fail_shots):
            img = _decode_b64_image(fail_shots[i])
            if img is None:
                img = _placeholder(CELL_W, CELL_H, i)
        else:
            img = _placeholder(CELL_W, CELL_H, i)

        img = img.resize((CELL_W, CELL_H), Image.LANCZOS)
        canvas.paste(img, (x, y))

    # 프레임 오버레이 (파일이 있을 때만)
    if os.path.exists(frame_path):
        frame = Image.open(frame_path).convert("RGBA")
        frame = frame.resize((CANVAS_W, CANVAS_H), Image.LANCZOS)
        canvas = canvas.convert("RGBA")
        canvas.paste(frame, (0, 0), mask=frame.split()[3])
        canvas = canvas.convert("RGB")

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()


def compose_from_game(
    fail_shots: list[str],
    user_name: str = "",
    clear_time_ms: Optional[int] = None,
) -> str:
    """
    게임 종료 후 인생네컷 생성 편의 함수.
    텍스트 워터마크(이름, 클리어 타임)를 추가한다.
    """
    b64 = compose_life_four_cut(fail_shots)

    # 워터마크 삽입
    data = base64.b64decode(b64)
    img = Image.open(io.BytesIO(data)).convert("RGB")
    draw = ImageDraw.Draw(img)

    watermark_lines = []
    if user_name:
        watermark_lines.append(user_name)
    if clear_time_ms is not None:
        secs = clear_time_ms / 1000
        watermark_lines.append(f"Clear: {secs:.2f}s")

    if watermark_lines:
        text = "  |  ".join(watermark_lines)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
        except Exception:
            font = ImageFont.load_default()

        margin = 8
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = img.width - tw - margin
        y = img.height - th - margin
        draw.rectangle([x - 4, y - 4, x + tw + 4, y + th + 4], fill=(0, 0, 0, 180))
        draw.text((x, y), text, fill=(255, 255, 255), font=font)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()
