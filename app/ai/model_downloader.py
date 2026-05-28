"""
MediaPipe face_landmarker.task 모델 파일 자동 다운로드 유틸리티.
서버 첫 실행 시 모델이 없으면 자동으로 받아온다.
"""
import os
import urllib.request

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
MODEL_DIR = "app/ai/models"
MODEL_PATH = os.path.join(MODEL_DIR, "face_landmarker.task")


def ensure_model() -> str:
    if os.path.exists(MODEL_PATH):
        return MODEL_PATH

    os.makedirs(MODEL_DIR, exist_ok=True)
    print(f"[model_downloader] Downloading face_landmarker.task ...")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    print(f"[model_downloader] Saved to {MODEL_PATH}")
    return MODEL_PATH
