"""
망한샷 + 인생네컷 합성 모듈.
- frame.png를 배경으로 사용, 4개의 투명 구멍에 이미지를 끼워 넣음
- 하단 여백: 날짜(좌) / QR코드(중앙) / 클리어 타임(우)
- frame.png가 없으면 다크 테마 폴백 레이아웃 사용
- 결과를 base64 JPEG으로 반환
"""
import base64
import io
import os
from datetime import datetime
from typing import Optional

import numpy as np
import qrcode
from PIL import Image, ImageDraw, ImageFont

FRAME_PATH = os.path.join(os.path.dirname(__file__), "assets", "frame.png")

# frame.png 실제 콘텐츠 너비 (우측 34px는 완전 투명 여백)
FRAME_W = 1872
FRAME_H = 5473

# frame.png 내 4개 사진 구멍 좌표 (x0, y0, x1, y1) — FRAME_W 기준
FRAME_HOLES = [
    (114, 159,  1757, 1232),
    (114, 1299, 1757, 2327),
    (114, 2394, 1757, 3422),
    (114, 3489, 1757, 4517),
]

# 하단 여백 영역 (frame.png row 4518~5472 = 높이 955px)
FOOTER_Y0 = 4518
FOOTER_Y1 = 5472

QR_SIZE = 160  # frame 원본 해상도 기준

# ── 폴백 레이아웃 상수 (frame.png 없을 때) ───────────────────
CANVAS_W, CANVAS_H = 800, 2200
TOP_PAD   = 60
CELL_PAD  = 40
CELL_GAP  = 30
CELL_W    = CANVAS_W - CELL_PAD * 2
CELL_H    = CELL_W * 9 // 16

COLOR_BG         = (20,  21,  24)
COLOR_GRID_LINE  = (32,  33,  38)
COLOR_TOP_BAR    = (28,  29,  34)
COLOR_DIVIDER    = (60,  62,  70)
COLOR_CELL_FRAME = (60,  64,  75)
COLOR_BRAND      = (255, 255, 255)
COLOR_BRAND_SHD  = (50,  50,  60)
COLOR_META_LABEL = (130, 135, 150)
COLOR_META_VALUE = (220, 220, 230)
COLOR_OUTER_LINE = (40,  44,  52)
COLOR_CELL_BG    = (35,  36,  42)


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _make_qr_image(url: str, size: int, bg_color=(255, 210, 127)) -> Image.Image:
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color=bg_color).convert("RGB")
    return qr_img.resize((size, size), Image.LANCZOS)


def _cover_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w, new_h = int(src_w * scale), int(src_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top  = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def _decode_b64_image(b64: str) -> Optional[Image.Image]:
    try:
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        data = base64.b64decode(b64)
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None


def _placeholder(width: int, height: int, index: int) -> Image.Image:
    img = Image.new("RGB", (width, height), color=COLOR_CELL_BG)
    draw = ImageDraw.Draw(img)
    font = _load_font(max(24, width // 12))
    text = f"#{index + 1}"
    bb = draw.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    draw.text(((width - tw) // 2, (height - th) // 2), text, fill=(80, 85, 100), font=font)
    return img


# ── frame.png 기반 합성 ───────────────────────────────────────

def _compose_with_frame(
    fail_shots: list[str],
    date_str: str,
    clear_str: str,
    video_url: Optional[str],
) -> str:
    frame_full = Image.open(FRAME_PATH).convert("RGBA")
    # 우측 투명 여백 제거 — 실제 콘텐츠 영역만 사용
    frame = frame_full.crop((0, 0, FRAME_W, FRAME_H))
    fw, fh = FRAME_W, FRAME_H

    # 사진을 frame 아래에 깔 베이스 캔버스 (RGB)
    base = Image.new("RGB", (fw, fh), color=(255, 210, 127))

    # 각 구멍에 사진 붙이기
    for i, (x0, y0, x1, y1) in enumerate(FRAME_HOLES):
        slot_w = x1 - x0
        slot_h = y1 - y0
        if i < len(fail_shots):
            img = _decode_b64_image(fail_shots[i])
            if img is None:
                img = _placeholder(slot_w, slot_h, i)
        else:
            img = _placeholder(slot_w, slot_h, i)

        img = _cover_crop(img, slot_w, slot_h)
        base.paste(img, (x0, y0))

    # frame 오버레이
    base = base.convert("RGBA")
    base.paste(frame, (0, 0), mask=frame.split()[3])
    canvas = base.convert("RGB")

    # 하단 여백 중앙에 PWEE + 날짜
    draw = ImageDraw.Draw(canvas)
    footer_h = FOOTER_Y1 - FOOTER_Y0

    font_brand = _load_font(200)
    font_date  = _load_font(80)
    text_color = (80, 50, 20)

    bb_brand = draw.textbbox((0, 0), "PWEE", font=font_brand)
    bw = bb_brand[2] - bb_brand[0]
    bh = bb_brand[3] - bb_brand[1]

    bb_date = draw.textbbox((0, 0), date_str, font=font_date)
    dw = bb_date[2] - bb_date[0]
    dh = bb_date[3] - bb_date[1]

    gap = 50
    total_h = bh + gap + dh
    # 발바닥 장식이 row 4871부터 시작하므로 그 위 영역 중앙에 배치
    clear_zone_h = 4871 - FOOTER_Y0  # 353px
    start_y = FOOTER_Y0 + (clear_zone_h - total_h) // 2 + 280

    # 캔버스 수평 중앙
    draw.text(((fw - bw) // 2, start_y), "PWEE", fill=text_color, font=font_brand)
    draw.text(((fw - dw) // 2, start_y + bh + gap), date_str, fill=text_color, font=font_date)

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=95)
    return base64.b64encode(buf.getvalue()).decode()


# ── 폴백: 다크 테마 레이아웃 ─────────────────────────────────

def _compose_fallback(
    fail_shots: list[str],
    date_str: str,
    clear_str: str,
    video_url: Optional[str],
) -> str:
    canvas_h = TOP_PAD + 4 * CELL_H + 3 * CELL_GAP + 160
    canvas = Image.new("RGB", (CANVAS_W, canvas_h), color=COLOR_BG)
    draw = ImageDraw.Draw(canvas, "RGBA")

    # 격자 패턴
    for x in range(0, CANVAS_W, 40):
        draw.line([(x, 0), (x, canvas_h)], fill=COLOR_GRID_LINE, width=1)
    for y in range(0, canvas_h, 40):
        draw.line([(0, y), (CANVAS_W, y)], fill=COLOR_GRID_LINE, width=1)

    # 상단 브랜드
    draw.rectangle([0, 0, CANVAS_W, TOP_PAD], fill=COLOR_TOP_BAR)
    font_brand = _load_font(32)
    brand = "PWEE"
    bb = draw.textbbox((0, 0), brand, font=font_brand)
    bw, bh = bb[2] - bb[0], bb[3] - bb[1]
    bx, by = (CANVAS_W - bw) // 2, (TOP_PAD - bh) // 2
    draw.text((bx + 2, by + 2), brand, fill=COLOR_BRAND_SHD, font=font_brand)
    draw.text((bx, by), brand, fill=COLOR_BRAND, font=font_brand)

    # 사진 셀
    for i in range(4):
        x = CELL_PAD
        y = TOP_PAD + i * (CELL_H + CELL_GAP)
        draw.rounded_rectangle(
            [x - 4, y - 4, x + CELL_W + 4, y + CELL_H + 4],
            radius=10, fill=COLOR_CELL_FRAME,
        )
        if i < len(fail_shots):
            img = _decode_b64_image(fail_shots[i])
            if img is None:
                img = _placeholder(CELL_W, CELL_H, i)
        else:
            img = _placeholder(CELL_W, CELL_H, i)
        img = _cover_crop(img, CELL_W, CELL_H)
        canvas.paste(img, (x, y))

    # 하단 바
    bar_y = TOP_PAD + 4 * CELL_H + 3 * CELL_GAP
    draw.rectangle([0, bar_y, CANVAS_W, canvas_h], fill=COLOR_TOP_BAR)
    center_y = bar_y + (canvas_h - bar_y) // 2
    font_label = _load_font(18)
    font_value = _load_font(26)

    if video_url:
        qr_img = _make_qr_image(video_url, 80, bg_color=(28, 29, 34))
        qr_x = (CANVAS_W - 80) // 2
        qr_y = bar_y + ((canvas_h - bar_y) - 80) // 2
        canvas.paste(qr_img, (qr_x, qr_y))

    if date_str:
        draw.text((CELL_PAD, center_y - 22), "DATE", fill=COLOR_META_LABEL, font=font_label)
        draw.text((CELL_PAD, center_y - 2), date_str, fill=COLOR_META_VALUE, font=font_value)

    if clear_str:
        bb = draw.textbbox((0, 0), clear_str, font=font_value)
        tw = bb[2] - bb[0]
        draw.text((CANVAS_W - tw - CELL_PAD, center_y - 22), "CLEAR",
                  fill=COLOR_META_LABEL, font=font_label)
        draw.text((CANVAS_W - tw - CELL_PAD, center_y - 2), clear_str,
                  fill=COLOR_META_VALUE, font=font_value)

    draw.rectangle([0, 0, CANVAS_W - 1, canvas_h - 1], outline=COLOR_OUTER_LINE, width=6)

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=95)
    return base64.b64encode(buf.getvalue()).decode()


# ── 공개 API ─────────────────────────────────────────────────

def compose_life_four_cut(
    fail_shots: list[str],
    date_str: str = "",
    clear_str: str = "",
    video_url: Optional[str] = None,
) -> str:
    """
    fail_shots : base64 이미지 리스트 (최대 4개)
    video_url  : QR로 삽입할 영상 URL (없으면 QR 생략)
    Returns    : base64 JPEG 문자열
    """
    if os.path.exists(FRAME_PATH):
        return _compose_with_frame(fail_shots, date_str, clear_str, video_url)
    return _compose_fallback(fail_shots, date_str, clear_str, video_url)


def compose_from_game(
    fail_shots: list[str],
    user_name: str = "",
    clear_time_ms: Optional[int] = None,
    video_url: Optional[str] = None,
) -> str:
    """게임 종료 후 인생네컷 생성 편의 함수."""
    date_str = datetime.now().strftime("%Y.%m.%d")

    if clear_time_ms is not None:
        secs = clear_time_ms / 1000
        minutes = int(secs // 60)
        seconds = secs % 60
        clear_str = f"{minutes:02d}:{seconds:05.2f}" if minutes > 0 else f"{seconds:.2f}s"
        if user_name:
            clear_str = f"{user_name}  {clear_str}"
    else:
        clear_str = user_name

    return compose_life_four_cut(fail_shots, date_str=date_str, clear_str=clear_str, video_url=video_url)
