import os
import time
import csv
import base64
import io
from datetime import datetime

import requests

# ============================================================
# CREDENTIALS (do not remove -- fill these via environment
# variables or Colab's `userdata` / secrets manager)
# ============================================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY_1", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY_1", "")

GOOGLE_DRIVE_CLIENT_ID = os.environ.get("GOOGLE_DRIVE_CLIENT_ID", "")
GOOGLE_DRIVE_CLIENT_SECRET = os.environ.get("GOOGLE_DRIVE_CLIENT_SECRET", "")
GOOGLE_DRIVE_REFRESH_TOKEN = os.environ.get("GOOGLE_DRIVE_REFRESH_TOKEN", "")
GOOGLE_DRIVE_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")  # optional

TEST_PROMPT = "Reply with a short one-line confirmation that you received this test message."
DELAY_SECONDS = 120

# ============================================================
# TEST IMAGE (small 2x2 red PNG, base64) -- used as the
# "screenshot" payload for multimodal test calls
# ============================================================
TEST_IMAGE_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR42mNk"
    "+A8EDAxUgFGVGIkGAA/YA/8B4L5cAAAAAElFTkSuQmCC"
)

GEMINI_MODELS = [
    "gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-3.1-flash-lite-preview",
    "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash",
    "gemini-robotics-er-2-preview", "gemini-2.5-pro", "gemini-3.0-pro",
    "gemini-3.0-flash", "gemini-3.0-flash-preview", "gemini-3.1-pro",
    "gemini-3.5-pro", "gemini-3.5-pro-preview", "gemini-3.6-pro",
    "gemini-3.7-pro", "gemini-3.7-pro-preview", "gemini-2.0-flash",
    "gemini-2.0-flash-lite", "gemini-2.0-pro-exp", "gemini-1.5-flash",
    "gemini-1.5-pro", "gemini-1.5-flash-8b", "gemini-embedding-001",
    "text-embedding-004", "multimodalembedding",
    "gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts",
    "gemini-3.0-flash-tts", "gemini-3.5-flash-tts", "gemini-3.6-flash-tts",
    "gemini-3.7-flash-tts", "veo-2.0-generate", "veo-3.0-generate",
    "veo-3.1-generate-preview", "imagen-3.0-generate-002",
    "imagen-3.5-generate", "imagen-4.0-generate-preview",
    "antigravity-preview-05-2026", "gemini-experimental",
    "gemini-2.0-flash-exp", "gemini-2.0-flash-thinking-exp",
    "gemini-3.0-ultra-preview", "gemini-3.5-ultra-preview",
    "gemini-3.7-ultra", "gemini-code-assist-2026", "gemini-robotics-er-1",
    "gemini-agent-preview", "gemini-live-audio-preview",
    "gemini-multimodal-live-2026", "gemini-1.0-pro",
    "gemini-1.0-pro-vision", "gemini-1.0-ultra", "gemini-1.5-pro-vision",
]

GROQ_MODELS = [
    "qwen/qwen3.6-27b", "qwen/qwen3.8-27b", "groq/compound",
    "groq/compound-mini", "openai/gpt-oss-120b", "openai/gpt-oss-20b",
    "canopylabs/orpheus-v1-english", "canopylabs/orpheus-arabic-saudi",
    "allam-2-7b", "meta-llama/llama-prompt-guard-2-86m",
    "meta-llama/llama-prompt-guard-2-22m", "openai/gpt-oss-safeguard-20b",
]


# ============================================================
# Google Drive uploader (OAuth refresh-token based, same
# pattern as the app's existing OneDriveClient)
# ============================================================
class GoogleDriveClient:
    def __init__(self):
        self.client_id = GOOGLE_DRIVE_CLIENT_ID
        self.client_secret = GOOGLE_DRIVE_CLIENT_SECRET
        self.refresh_token = GOOGLE_DRIVE_REFRESH_TOKEN
        self.folder_id = GOOGLE_DRIVE_FOLDER_ID
        self.access_token = None

    def is_configured(self):
        return bool(self.client_id and self.client_secret and self.refresh_token)

    def get_access_token(self):
        if not self.is_configured():
            return None
        url = "https://oauth2.googleapis.com/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }
        try:
            res = requests.post(url, data=data, timeout=15)
            res.raise_for_status()
            self.access_token = res.json().get("access_token")
            return self.access_token
        except Exception as e:
            print(f"[Google Drive] Token refresh failed: {e}")
            return None

    def upload_file(self, local_path, remote_name):
        token = self.access_token or self.get_access_token()
        if not token:
            print("[Google Drive] Not configured or token unavailable -- skipping upload.")
            return False

        metadata = {"name": remote_name}
        if self.folder_id:
            metadata["parents"] = [self.folder_id]

        try:
            import json as _json
            boundary = "jarvis_test_upload_boundary"
            with open(local_path, "rb") as f:
                file_data = f.read()

            body = (
                f"--{boundary}\r\n"
                f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{_json.dumps(metadata)}\r\n"
                f"--{boundary}\r\n"
                f"Content-Type: text/csv\r\n\r\n"
            ).encode("utf-8") + file_data + f"\r\n--{boundary}--".encode("utf-8")

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            }
            res = requests.post(
                "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
                headers=headers, data=body, timeout=60
            )
            if res.status_code in (200, 201):
                print(f"[Google Drive] Uploaded '{remote_name}' successfully.")
                return True
            print(f"[Google Drive] Upload failed: HTTP {res.status_code} - {res.text[:200]}")
            return False
        except Exception as e:
            print(f"[Google Drive] Upload error: {e}")
            return False


# ============================================================
# Model test calls
# ============================================================
def test_gemini_model(model_name):
    """Single call, text + image together. Returns (status, detail)."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [
                {"text": TEST_PROMPT},
                {"inline_data": {"mime_type": "image/png", "data": TEST_IMAGE_BASE64}}
            ]
        }]
    }
    try:
        res = requests.post(url, json=payload, timeout=30)
        if res.status_code == 200:
            try:
                text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                return "Vision Active", text[:200]
            except Exception:
                return "Vision Active", "(response received, could not parse text)"

        body_lower = res.text.lower()
        if res.status_code == 400 and ("image" in body_lower or "inline_data" in body_lower or "multimodal" in body_lower):
            # Retry as text-only
            text_payload = {"contents": [{"parts": [{"text": TEST_PROMPT}]}]}
            res2 = requests.post(url, json=text_payload, timeout=30)
            if res2.status_code == 200:
                return "Text Active", "[Text Only / Vision Not Supported]"
            return "Error", f"HTTP {res.status_code} (vision) / HTTP {res2.status_code} (text): {res.text[:150]}"

        return "Error", f"HTTP {res.status_code}: {res.text[:200]}"
    except Exception as e:
        return "Error", str(e)[:200]


def test_groq_model(model_name):
    """Single call, text-only (Groq chat models here are not vision
    endpoints); errors are still caught so the script never crashes."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model_name, "messages": [{"role": "user", "content": TEST_PROMPT}]}
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=30)
        if res.status_code == 200:
            try:
                text = res.json()["choices"][0]["message"]["content"]
                return "Text Active", text[:200]
            except Exception:
                return "Text Active", "(response received, could not parse text)"
        return "Error", f"HTTP {res.status_code}: {res.text[:200]}"
    except Exception as e:
        return "Error", str(e)[:200]


# ============================================================
# Main test loop
# ============================================================
def run_all_tests():
    all_models = [("gemini", m) for m in GEMINI_MODELS] + [("groq", m) for m in GROQ_MODELS]
    total = len(all_models)
    results = []

    print(f"Starting test of {total} models. Estimated time: ~{(total * DELAY_SECONDS) / 3600:.2f} hours.\n")

    for idx, (provider, model_name) in enumerate(all_models, start=1):
        print(f"[{idx}/{total}] Testing {provider}: {model_name} ...")

        try:
            if provider == "gemini":
                status, detail = test_gemini_model(model_name)
            else:
                status, detail = test_groq_model(model_name)
        except Exception as e:
            status, detail = "Error", f"Unhandled exception: {str(e)[:200]}"

        print(f"    -> {status}: {detail[:100]}")
        results.append({
            "provider": provider,
            "model_name": model_name,
            "status": status,
            "detail": detail,
            "tested_at": datetime.now().isoformat(),
        })

        if idx < total:
            print(f"    Waiting {DELAY_SECONDS}s before next call...\n")
            time.sleep(DELAY_SECONDS)

    return results


def save_results_csv(results):
    filename = f"jarvis_model_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["provider", "model_name", "status", "detail", "tested_at"])
        writer.writeheader()
        writer.writerows(results)
    print(f"\nResults saved locally to: {filename}")
    return filename


def main():
    if not GEMINI_API_KEY:
        print("WARNING: GEMINI_API_KEY not set -- all Gemini calls will fail.")
    if not GROQ_API_KEY:
        print("WARNING: GROQ_API_KEY not set -- all Groq calls will fail.")

    results = run_all_tests()
    csv_path = save_results_csv(results)

    drive = GoogleDriveClient()
    if drive.is_configured():
        drive.upload_file(csv_path, os.path.basename(csv_path))
    else:
        print("[Google Drive] Client ID/Secret/Refresh Token not set -- skipping Drive upload. "
              "CSV is still saved locally above.")

    print("\nDone.")


if __name__ == "__main__":
    main()
