"""
사진/영상 공유 API

POST /api/share/upload              이미지 저장 + QR 코드 생성
GET  /api/share/download/<id>       이미지 다운로드
POST /api/share/upload-video        영상(webm/mp4) 저장
GET  /api/share/video/<game_id>     영상 스트리밍/다운로드
POST /api/share/email               이메일 전송
"""
import base64
import io
import os
import uuid

import qrcode
from flask import Blueprint, current_app, jsonify, request, send_file
from PIL import Image

share_bp = Blueprint("share", __name__, url_prefix="/api/share")

PHOTO_DIR = os.path.join("static", "images", "photo")
QR_DIR    = os.path.join("static", "images", "qrcode")
VIDEO_DIR = os.path.join("static", "videos")


def _ensure_dirs():
    os.makedirs(PHOTO_DIR, exist_ok=True)
    os.makedirs(QR_DIR, exist_ok=True)
    os.makedirs(VIDEO_DIR, exist_ok=True)


def _decode_b64(b64: str) -> bytes:
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    return base64.b64decode(b64)


@share_bp.post("/upload")
def upload():
    """
    JSON body: { image_base64, video_id?, user_name? }
    Returns: { image_id, qr_b64, share_url }
    """
    data = request.get_json(force=True)
    b64 = data.get("image_base64", "")
    if not b64:
        return jsonify({"error": "image_base64가 필요합니다."}), 400

    _ensure_dirs()

    image_id   = uuid.uuid4().hex[:10]
    image_path = os.path.join(PHOTO_DIR, f"{image_id}.png")

    try:
        img = Image.open(io.BytesIO(_decode_b64(b64)))
        img.save(image_path)
    except Exception:
        return jsonify({"error": "이미지 저장에 실패했습니다."}), 500

    # video_id 저장 (같은 이름으로 메타 파일)
    video_id = (data.get("video_id") or "").strip()
    if video_id:
        meta_path = os.path.join(PHOTO_DIR, f"{image_id}.meta")
        with open(meta_path, "w") as f:
            f.write(video_id)

    server_url = os.getenv("SERVER_URL", "http://localhost:5001")
    share_url  = f"{server_url}/api/share/page/{image_id}"

    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(share_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")

    qr_buf = io.BytesIO()
    qr_img.save(qr_buf, format="PNG")
    qr_b64 = base64.b64encode(qr_buf.getvalue()).decode()

    return jsonify({
        "image_id":  image_id,
        "qr_b64":    qr_b64,
        "share_url": share_url,
    })


@share_bp.get("/page/<image_id>")
def share_page(image_id: str):
    image_path = os.path.join(PHOTO_DIR, f"{image_id}.png")
    if not os.path.isfile(image_path):
        return "<h2>사진을 찾을 수 없습니다.</h2>", 404

    server_url   = os.getenv("SERVER_URL", "http://localhost:5001")
    photo_url    = f"{server_url}/api/share/download/{image_id}"

    meta_path = os.path.join(PHOTO_DIR, f"{image_id}.meta")
    video_block = ""
    if os.path.isfile(meta_path):
        with open(meta_path) as f:
            vid = f.read().strip()
        if vid:
            video_url      = f"{server_url}/api/share/video/{vid}"
            video_dl_url   = f"{server_url}/api/share/video/{vid}?download=1"
            video_block = f"""
            <video src="{video_url}" controls style="width:100%;max-width:480px;border-radius:12px;margin-top:16px"></video>
            <a href="{video_dl_url}" download class="btn">🎬 동영상 다운로드</a>"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pwee — 사진 & 영상 공유</title>
  <style>
    body {{ font-family: 'Noto Sans KR', sans-serif; background:#fffdf2; display:flex; flex-direction:column; align-items:center; padding:24px; gap:16px; color:#463c3c; }}
    h1 {{ font-size:24px; margin:0; }}
    img {{ width:100%; max-width:360px; border-radius:12px; box-shadow:0 4px 16px rgba(0,0,0,.12); }}
    .btn {{ display:block; width:100%; max-width:360px; padding:14px; background:#463c3c; color:#fffdf2; border-radius:999px; text-align:center; text-decoration:none; font-size:16px; box-sizing:border-box; }}
  </style>
</head>
<body>
  <h1>Pwee 📸</h1>
  <img src="{photo_url}" alt="인생네컷">
  <a href="{photo_url}" download class="btn">🖼 사진 다운로드</a>
  {video_block}
</body>
</html>"""
    from flask import Response
    return Response(html, mimetype="text/html")


@share_bp.get("/download/<image_id>")
def download(image_id: str):
    image_path = os.path.join(PHOTO_DIR, f"{image_id}.png")
    if not os.path.isfile(image_path):
        return jsonify({"error": "이미지를 찾을 수 없습니다."}), 404
    return send_file(os.path.abspath(image_path), mimetype="image/png")


@share_bp.post("/upload-video")
def upload_video():
    """
    multipart/form-data: file(webm/mp4) + game_id
    Returns: { game_id, video_url }
    """
    _ensure_dirs()

    game_id = request.form.get("game_id", "").strip()
    if not game_id:
        return jsonify({"error": "game_id가 필요합니다."}), 400

    video_file = request.files.get("file")
    if not video_file:
        return jsonify({"error": "file이 필요합니다."}), 400

    ext = "webm"
    original_filename = video_file.filename or ""
    if original_filename.lower().endswith(".mp4"):
        ext = "mp4"

    filename = f"{game_id}.{ext}"
    save_path = os.path.join(VIDEO_DIR, filename)

    try:
        video_file.save(save_path)
    except Exception:
        return jsonify({"error": "영상 저장에 실패했습니다."}), 500

    server_url = os.getenv("SERVER_URL", "http://localhost:5001")
    video_url  = f"{server_url}/api/share/video/{game_id}"

    return jsonify({
        "game_id":   game_id,
        "video_url": video_url,
    })


@share_bp.get("/video/<game_id>")
def stream_video(game_id: str):
    """
    ?download=1  →  파일 다운로드 (Content-Disposition: attachment)
    기본값       →  인라인 스트리밍
    """
    as_download = request.args.get("download", "").lower() in ("1", "true", "yes")
    for ext in ("webm", "mp4"):
        path = os.path.join(VIDEO_DIR, f"{game_id}.{ext}")
        if os.path.isfile(path):
            mimetype = "video/webm" if ext == "webm" else "video/mp4"
            return send_file(
                os.path.abspath(path),
                mimetype=mimetype,
                as_attachment=as_download,
                download_name=f"pwee-{game_id}.{ext}" if as_download else None,
            )
    return jsonify({"error": "영상을 찾을 수 없습니다."}), 404


@share_bp.post("/email")
def send_email():
    """
    JSON body: { email, image_id?, image_base64?, video_id? }
    사진과 동영상(있으면) 모두 첨부.
    """
    from flask_mail import Message
    from app import mail

    data  = request.get_json(force=True)
    email = (data.get("email") or "").strip()
    if not email or "@" not in email:
        return jsonify({"error": "올바른 이메일 주소가 필요합니다."}), 400

    # 이미지 바이트 획득
    img_bytes = None
    b64 = data.get("image_base64", "")
    if b64:
        try:
            img_bytes = _decode_b64(b64)
        except Exception:
            return jsonify({"error": "이미지 디코딩에 실패했습니다."}), 400
    else:
        image_id = data.get("image_id", "")
        if image_id:
            path = os.path.join(PHOTO_DIR, f"{image_id}.png")
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    img_bytes = f.read()

    if not img_bytes:
        return jsonify({"error": "전송할 이미지가 없습니다."}), 400

    # 동영상 바이트 획득 (선택)
    video_bytes = None
    video_ext   = "webm"
    video_id = (data.get("video_id") or "").strip()
    if video_id:
        for ext in ("webm", "mp4"):
            vpath = os.path.join(VIDEO_DIR, f"{video_id}.{ext}")
            if os.path.isfile(vpath):
                with open(vpath, "rb") as f:
                    video_bytes = f.read()
                video_ext = ext
                break

    server_url = os.getenv("SERVER_URL", "http://localhost:5001")
    has_video  = video_bytes is not None

    body_text = (
        "Pwee에서 찍은 사진과 영상을 공유해 드립니다 :)\n\n"
        f"📥 다운로드 페이지: {server_url}/api/share/page/{data.get('image_id', '')}"
        if has_video else
        "Pwee에서 찍은 사진을 공유해 드립니다 :)"
    )

    sender = current_app.config.get("MAIL_DEFAULT_SENDER") or current_app.config.get("MAIL_USERNAME")
    msg = Message(
        subject="Pwee — 사진" + (" & 영상" if has_video else ""),
        sender=sender,
        recipients=[email],
        body=body_text,
    )
    msg.attach("pwee-photo.png", "image/png", img_bytes)
    if video_bytes:
        mimetype = f"video/{video_ext}"
        msg.attach(f"pwee-video.{video_ext}", mimetype, video_bytes)

    try:
        mail.send(msg)
    except Exception as e:
        return jsonify({"error": f"메일 전송 실패: {e}"}), 500

    return jsonify({"message": "메일이 전송되었습니다."})