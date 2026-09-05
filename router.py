import os
import re
import json

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
    "Llama, or any underlying model/provider name. Keep responses clean, "
    "structured, and in the user's language (Hindi/English/Hinglish). Never "
    "output internal reasoning or <think> tags."
)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
SKIP_STATUS = {400, 401, 402, 404}


def strip_think_tags(text):
    if not text:
        return text
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"</?think>", "", cleaned, flags=re.IGNORECASE).strip()


class SmartAIRouter:
    """Fallback order per spec: Gemini -> OpenRouter -> Groq.
    429 / 5xx errors are treated as retryable (try next key/provider);
    400/401/402/404 are treated as permanent for that key (skip immediately)."""

    def __init__(self):
        self.mode = "auto"
        self._manual_overrides = {}

    def set_mode(self, mode):
        self.mode = mode

    def set_manual_key(self, provider_name, key):
        if provider_name not in ("gemini", "groq", "openrouter"):
            return False
        self._manual_overrides[provider_name] = key
        return True

    def _key_for(self, provider, env_name):
        return self._manual_overrides.get(provider) or load_key(env_name)

    def _build_chain(self):
        chain = [
            ("gemini", self._key_for("gemini", "GEMINI_API_KEY_1"), "gemini-2.5-flash", self._call_gemini),
            ("gemini", self._key_for("gemini", "GEMINI_API_KEY_2"), "gemini-2.5-flash", self._call_gemini),
            ("openrouter", self._key_for("openrouter", "OPENROUTER_API_KEY_1"), "google/gemini-2.5-flash:free", self._call_openrouter),
            ("openrouter", self._key_for("openrouter", "OPENROUTER_API_KEY_2"), "meta-llama/llama-3.3-70b-instruct:free", self._call_openrouter),
            ("groq", self._key_for("groq", "GROQ_API_KEY_1"), "llama3-8b-8192", self._call_groq),
            ("groq", self._key_for("groq", "GROQ_API_KEY_2"), "llama3-8b-8192", self._call_groq),
        ]
        if self.mode != "auto":
            chain = [c for c in chain if c[0] == self.mode] or chain
        return chain

    def _to_messages(self, prompt, context):
        messages = [{"role": "system", "content": SYSTEM_PROMPT_JARVIS}]
        for role, content in (context or []):
            messages.append({"role": "user" if role == "user" else "assistant", "content": content})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _call_gemini(self, key, model, prompt, context):
        import requests
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT_JARVIS}]},
            "contents": [{"parts": [{"text": prompt}]}]
        }
        res = requests.post(url, json=payload, timeout=10, verify=False)
        if res.status_code >= 400:
            raise self._http_error(res.status_code)
        return res.json()["candidates"][0]["content"]["parts"][0]["text"]

    def _call_groq(self, key, model, prompt, context):
        import requests
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": self._to_messages(prompt, context)}
        res = requests.post(url, json=payload, headers=headers, timeout=10, verify=False)
        if res.status_code >= 400:
            raise self._http_error(res.status_code)
        return res.json()["choices"][0]["message"]["content"]

    def _call_openrouter(self, key, model, prompt, context):
        import requests
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": self._to_messages(prompt, context)}
        res = requests.post(url, json=payload, headers=headers, timeout=10, verify=False)
        if res.status_code >= 400:
            raise self._http_error(res.status_code)
        return res.json()["choices"][0]["message"]["content"]

    class _HttpError(Exception):
        def __init__(self, status):
            self.status = status
            super().__init__(f"HTTP {status}")

    def _http_error(self, status):
        return self._HttpError(status)

    def ask(self, prompt, context=None):
        """Returns (reply_or_None, fail_count)."""
        chain = self._build_chain()
        fail_count = 0

        for provider, key, model, call_fn in chain:
            if not key:
                fail_count += 1
                continue
            try:
                reply = call_fn(key, model, prompt, context)
                return strip_think_tags(reply), fail_count
            except self._HttpError:
                fail_count += 1
                continue
            except Exception:
                fail_count += 1
                continue

        return None, fail_count
