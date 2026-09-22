import os
import time
import csv
import json
import threading
from datetime import datetime, timedelta

import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY_1", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY_1", "")

GOOGLE_DRIVE_CLIENT_ID = os.environ.get("GOOGLE_DRIVE_CLIENT_ID", "")
GOOGLE_DRIVE_CLIENT_SECRET = os.environ.get("GOOGLE_DRIVE_CLIENT_SECRET", "")
GOOGLE_DRIVE_REFRESH_TOKEN = os.environ.get("GOOGLE_DRIVE_REFRESH_TOKEN", "")
GOOGLE_DRIVE_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")

TEST_PROMPT = "Reply with a short one-line confirmation that you received this test message."
DELAY_SECONDS = 120
RESUME_WINDOW_HOURS = 24

PROGRESS_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_progress.json")

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

ALL_MODELS = [("gemini", m) for m in GEMINI_MODELS] + [("groq", m) for m in GROQ_MODELS]
TOTAL_MODELS = len(ALL_MODELS)


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
        except Exception:
            return None

    def upload_file(self, local_path, remote_name, mime_type="text/csv"):
        token = self.access_token or self.get_access_token()
        if not token:
            return False
        metadata = {"name": remote_name}
        if self.folder_id:
            metadata["parents"] = [self.folder_id]
        try:
            boundary = "jarvis_test_upload_boundary"
            with open(local_path, "rb") as f:
                file_data = f.read()
            body = (
                f"--{boundary}\r\n"
                f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{json.dumps(metadata)}\r\n"
                f"--{boundary}\r\n"
                f"Content-Type: {mime_type}\r\n\r\n"
            ).encode("utf-8") + file_data + f"\r\n--{boundary}--".encode("utf-8")
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            }
            res = requests.post(
                "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
                headers=headers, data=body, timeout=60
            )
            return res.status_code in (200, 201)
        except Exception:
            return False


def load_progress():
    if not os.path.exists(PROGRESS_FILE_PATH):
        return {}
    try:
        with open(PROGRESS_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_progress_entry(progress, model_key, entry):
    progress[model_key] = entry
    try:
        with open(PROGRESS_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def is_recently_tested(entry):
    if not entry:
        return False
    try:
        tested_at = datetime.fromisoformat(entry.get("last_tested_at", ""))
    except Exception:
        return False
    return (datetime.now() - tested_at) < timedelta(hours=RESUME_WINDOW_HOURS)


def test_gemini_model(model_name):
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
            text_payload = {"contents": [{"parts": [{"text": TEST_PROMPT}]}]}
            res2 = requests.post(url, json=text_payload, timeout=30)
            if res2.status_code == 200:
                return "Text Active", "[Text Only / Vision Not Supported]"
            return "Error", f"HTTP {res.status_code} (vision) / HTTP {res2.status_code} (text): {res.text[:150]}"

        return "Error", f"HTTP {res.status_code}: {res.text[:200]}"
    except Exception as e:
        return "Error", str(e)[:200]


def test_groq_model(model_name):
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


def save_results_csv(progress):
    filename = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"jarvis_model_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["provider", "model_id", "status", "response_detail", "last_tested_at"])
        writer.writeheader()
        for model_key, entry in progress.items():
            writer.writerow({
                "provider": entry.get("provider", ""),
                "model_id": entry.get("model_id", model_key),
                "status": entry.get("status", ""),
                "response_detail": entry.get("response_detail", ""),
                "last_tested_at": entry.get("last_tested_at", ""),
            })
    return filename


def upload_final_artifacts(csv_path):
    drive = GoogleDriveClient()
    if not drive.is_configured():
        return False, False
    csv_ok = drive.upload_file(csv_path, os.path.basename(csv_path), mime_type="text/csv")
    json_ok = drive.upload_file(PROGRESS_FILE_PATH, "test_progress.json", mime_type="application/json")
    return csv_ok, json_ok


def run_all_tests(progress_callback=None, stop_flag=None):
    """
    progress_callback(current_index, total, model_id, status, detail, percent)
    is invoked after every single model test (including skipped ones).
    stop_flag is an optional callable; if it returns True the loop exits
    early (progress already saved incrementally, so it resumes cleanly).
    """
    progress = load_progress()

    for idx, (provider, model_name) in enumerate(ALL_MODELS, start=1):
        if stop_flag is not None and stop_flag():
            break

        model_key = f"{provider}:{model_name}"
        existing_entry = progress.get(model_key)

        if is_recently_tested(existing_entry):
            percent = round((idx / TOTAL_MODELS) * 100, 1)
            if progress_callback:
                progress_callback(idx, TOTAL_MODELS, model_name, existing_entry.get("status", "Skipped"),
                                   existing_entry.get("response_detail", ""), percent)
            continue

        try:
            if provider == "gemini":
                status, detail = test_gemini_model(model_name)
            else:
                status, detail = test_groq_model(model_name)
        except Exception as e:
            status, detail = "Error", f"Unhandled exception: {str(e)[:200]}"

        entry = {
            "model_id": model_name,
            "provider": provider,
            "last_tested_at": datetime.now().isoformat(),
            "status": status,
            "response_detail": detail,
        }
        save_progress_entry(progress, model_key, entry)

        percent = round((idx / TOTAL_MODELS) * 100, 1)
        if progress_callback:
            progress_callback(idx, TOTAL_MODELS, model_name, status, detail, percent)

        if idx < TOTAL_MODELS:
            waited = 0
            while waited < DELAY_SECONDS:
                if stop_flag is not None and stop_flag():
                    break
                time.sleep(1)
                waited += 1

    csv_path = save_results_csv(progress)
    upload_final_artifacts(csv_path)
    return csv_path


def run_in_background_thread(progress_callback=None, stop_flag=None):
    t = threading.Thread(target=run_all_tests, kwargs={
        "progress_callback": progress_callback,
        "stop_flag": stop_flag,
    }, daemon=True, name="ModelTesterThread")
    t.start()
    return t


if __name__ == "__main__":
    def _print_progress(idx, total, model_name, status, detail, percent):
        print(f"[{idx}/{total}] {model_name} -> {status} ({percent}%)")

    run_all_tests(progress_callback=_print_progress)
