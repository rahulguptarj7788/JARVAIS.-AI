import os
import re
import json
import time
import threading

APP_KEYS_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_keys.json")

_APP_KEYS_JSON = {}
try:
    if os.path.exists(APP_KEYS_JSON_PATH):
        with open(APP_KEYS_JSON_PATH, "r", encoding="utf-8") as f:
            _APP_KEYS_JSON = json.load(f)
except Exception:
    _APP_KEYS_JSON = {}


def load_key(name):
    return _APP_KEYS_JSON.get(name) or os.environ.get(name)


SYSTEM_PROMPT_JARVIS = (
    "You are Jarvis, a highly capable AI assistant powering a mobile app. "
    "Always identify yourself as Jarvis. Never mention Claude, ChatGPT, Gemini, "
    "Groq, or any underlying model/provider name. Keep responses clean, "
    "structured, and in the user's language (Hindi/English/Hinglish). Never "
    "output internal reasoning or <think> tags."
)

SKIP_STATUS = {400, 401, 402, 404}
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Per your Colab verification. Used exactly as given -- if any of these
# turn out wrong on Google's side, the request will 404/400 and the
# router will simply skip to the next model/key, not crash.
GEMINI_TEXT_MODELS = [
    "models/gemini-3.5-flash",
    "models/gemini-3.6-flash",
    "models/gemini-3.7-flash",
]
GEMINI_VISION_MODELS = [
    "models/gemini-3.1-flash-lite",
    "models/gemini-3.1-flash-lite-preview",
    "models/gemini-robotics-er-2-preview",
]
GROQ_TEXT_MODELS = [
    "qwen/qwen3.6-27b",
    "groq/compound",
    "openai/gpt-oss-120b",
]
GROQ_STT_MODEL = "whisper-large-v3-turbo"

RPM_LIMIT_PER_KEY = 14      # proactively rotate before hitting the real 15/min cap
RPM_WINDOW_SECONDS = 60


def strip_think_tags(text):
    if not text:
        return text
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"</?think>", "", cleaned, flags=re.IGNORECASE).strip()


class ProviderHttpError(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__(f"HTTP {status}")


class KeyPoolCounter:
    """
    Tracks request counts per key inside a rolling 60s window and forces
    a switch to the next key in the pool BEFORE the real 429 happens
    (proactive rotation at 14 requests instead of reacting to errors).
    Thread-safe: called from whichever thread is making the API call.
    """
    def __init__(self, keys):
        self._keys = [k for k in keys if k]
        self._lock = threading.Lock()
        self._state = {k: {"count": 0, "window_start": time.time()} for k in self._keys}
        self._pointer = 0

    def _reset_if_expired(self, key):
        state = self._state[key]
        if time.time() - state["window_start"] >= RPM_WINDOW_SECONDS:
            state["count"] = 0
            state["window_start"] = time.time()

    def get_available_keys_in_order(self):
        """Returns keys starting from whichever one currently has quota
        left, so the caller always tries an under-limit key first."""
        if not self._keys:
            return []
        with self._lock:
            for k in self._keys:
                self._reset_if_expired(k)
            ordered = sorted(
                self._keys,
                key=lambda k: (self._state[k]["count"] >= RPM_LIMIT_PER_KEY, self._state[k]["count"])
            )
            return ordered

    def record_request(self, key):
        with self._lock:
            if key in self._state:
                self._reset_if_expired(key)
                self._state[key]["count"] += 1


class SmartAIRouter:
    """
    Exactly 2 providers, 2 keys each: Gemini (GEMINI_KEY_1/2) and Groq
    (GROQ_KEY_1/2). OpenRouter and Cerebras are fully removed per
    updated requirements. Failover chain: Gemini text models -> Groq
    text models. Each provider proactively rotates between its 2 keys
    at 14 requests/minute rather than waiting for a 429.
    """

    def __init__(self):
        self.mode = "auto"
        self._manual_overrides = {}

        gemini_keys = [load_key("GEMINI_KEY_1"), load_key("GEMINI_KEY_2")]
        groq_keys = [load_key("GROQ_KEY_1"), load_key("GROQ_KEY_2")]

        self._gemini_counter = KeyPoolCounter(gemini_keys)
        self._groq_counter = KeyPoolCounter(groq_keys)

    def set_mode(self, mode):
        self.mode = mode

    def set_manual_key(self, provider_name, key):
        if provider_name not in ("gemini", "groq"):
            return False
        self._manual_overrides[provider_name] = key
        return True

    def _requests_kwargs(self, extra_headers=None):
        import certifi
        kwargs = {"timeout": 10, "verify": certifi.where()}
        if extra_headers:
            kwargs["headers"] = extra_headers
        return kwargs

    # ---------------- Gemini ----------------
    def _call_gemini(self, key, model, prompt, context):
        import requests
        url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={key}"
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT_JARVIS}]},
            "contents": [{"parts": [{"text": prompt}]}]
        }
        res = requests.post(url, json=payload, **self._requests_kwargs())
        if res.status_code >= 400:
            raise ProviderHttpError(res.status_code)
        return res.json()["candidates"][0]["content"]["parts"][0]["text"]

    def analyze_image_gemini(self, key, model, image_base64, prompt):
        """Vision/screen-analysis call. Not yet wired into the UI --
        exposed here so it can be hooked up to the screenshot feature
        in a later pass without touching router internals again."""
        import requests
        url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={key}"
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/png", "data": image_base64}}
                ]
            }]
        }
        res = requests.post(url, json=payload, **self._requests_kwargs())
        if res.status_code >= 400:
            raise ProviderHttpError(res.status_code)
        return res.json()["candidates"][0]["content"]["parts"][0]["text"]

    # ---------------- Groq (text) ----------------
    def _to_messages(self, prompt, context):
        messages = [{"role": "system", "content": SYSTEM_PROMPT_JARVIS}]
        for role, content in (context or []):
            messages.append({"role": "user" if role == "user" else "assistant", "content": content})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _call_groq(self, key, model, prompt, context):
        import requests
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": self._to_messages(prompt, context)}
        res = requests.post(url, json=payload, **self._requests_kwargs(headers))
        if res.status_code >= 400:
            raise ProviderHttpError(res.status_code)
        return res.json()["choices"][0]["message"]["content"]

    # ---------------- Groq (STT) ----------------
    def transcribe_audio_groq(self, key, audio_file_path):
        """Speech-to-text via Groq Whisper. Custom User-Agent header is
        required -- Cloudflare in front of Groq's API returns 403 to
        requests using Python's default 'python-requests/x.y' UA."""
        import requests
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {
            "Authorization": f"Bearer {key}",
            "User-Agent": "JarvisAI-Android/1.0 (+com.jarvis.assistant)",
        }
        with open(audio_file_path, "rb") as f:
            files = {"file": f}
            data = {"model": GROQ_STT_MODEL}
            import certifi
            res = requests.post(url, headers=headers, files=files, data=data,
                                 timeout=15, verify=certifi.where())
        if res.status_code >= 400:
            raise ProviderHttpError(res.status_code)
        return res.json().get("text", "")

    # ---------------- Failover chain ----------------
    def _build_chain(self):
        chain = []

        if self.mode in ("auto", "gemini"):
            gemini_key = self._manual_overrides.get("gemini")
            gemini_keys_ordered = [gemini_key] if gemini_key else self._gemini_counter.get_available_keys_in_order()
            for key in gemini_keys_ordered:
                for model in GEMINI_TEXT_MODELS:
                    chain.append({"provider": "gemini", "key": key, "model": model, "call": self._call_gemini})

        if self.mode in ("auto", "groq"):
            groq_key = self._manual_overrides.get("groq")
            groq_keys_ordered = [groq_key] if groq_key else self._groq_counter.get_available_keys_in_order()
            for key in groq_keys_ordered:
                for model in GROQ_TEXT_MODELS:
                    chain.append({"provider": "groq", "key": key, "model": model, "call": self._call_groq})

        return chain

    def ask(self, prompt, context=None):
        """Returns (reply_or_None, fail_count)."""
        chain = self._build_chain()
        fail_count = 0

        for entry in chain:
            key = entry["key"]
            if not key:
                fail_count += 1
                continue
            try:
                reply = entry["call"](key, entry["model"], prompt, context)
                if entry["provider"] == "gemini":
                    self._gemini_counter.record_request(key)
                else:
                    self._groq_counter.record_request(key)
                return strip_think_tags(reply), fail_count
            except ProviderHttpError as e:
                fail_count += 1
                if e.status in SKIP_STATUS:
                    continue
                if e.status in RETRYABLE_STATUS:
                    continue
                continue
            except Exception:
                fail_count += 1
                continue

        return None, fail_count

    # ---------------- OneDrive (preserved, unchanged from before) ----------------
    def onedrive_is_configured(self):
        return self.onedrive.is_configured() if hasattr(self, "onedrive") else False

    def onedrive_upload(self, local_path, remote_name):
        return self.onedrive.upload_file(local_path, remote_name) if hasattr(self, "onedrive") else False
