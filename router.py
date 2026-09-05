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
    """No SQLite (zero-disk-storage requirement): only bundled
    app_keys.json (from GitHub Secrets at build time) or os.environ."""
    return _APP_KEYS_JSON.get(name) or os.environ.get(name)


SYSTEM_PROMPT_JARVIS = (
    "You are Jarvis, a highly capable AI assistant powering a mobile app. "
    "Always identify yourself as Jarvis. Never mention Claude, ChatGPT, Gemini, "
    "Llama, or any underlying model/provider name. Maintain a helpful, respectful, "
    "futuristic assistant tone. Match the user's language (Hindi, English, or "
    "Hinglish) based on how they wrote to you. Keep responses clean and structured "
    "-- never output internal reasoning, <think> tags, or meta-commentary."
)


def strip_think_tags(text):
    if not text:
        return text
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"</?think>", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


class SmartAIRouter:
    """Sequential 6-key fallback, exactly in this order:
    Gemini K1 -> Gemini K2 -> Groq K1 -> Groq K2 -> OpenRouter K1 -> OpenRouter K2.
    Manual overrides set via 'set api <provider> <key>' live only in RAM
    (self._manual_overrides) -- lost on app restart, per zero-disk-storage.
    """

    def __init__(self):
        self.mode = "auto"
        self._manual_overrides = {}  # provider -> key, RAM only

    def set_mode(self, mode):
        self.mode = mode

    def set_manual_key(self, provider_name, key):
        if provider_name not in ("gemini", "groq", "openrouter"):
            return False
        self._manual_overrides[provider_name] = key
        return True

    def _key_for(self, provider, slot_env_name):
        if provider in self._manual_overrides:
            return self._manual_overrides[provider]
        return load_key(slot_env_name)

    def _build_chain(self):
        chain = [
            ("gemini", self._key_for("gemini", "GEMINI_API_KEY_1"), "gemini-2.5-flash", self._call_gemini),
            ("gemini", self._key_for("gemini", "GEMINI_API_KEY_2"), "gemini-2.5-flash", self._call_gemini),
            ("groq", self._key_for("groq", "GROQ_API_KEY_1"), "qwen/qwen3.6-27b", self._call_groq),
            ("groq", self._key_for("groq", "GROQ_API_KEY_2"), "qwen/qwen3.6-27b", self._call_groq),
            ("openrouter", self._key_for("openrouter", "OPENROUTER_API_KEY_1"), "google/gemini-2.5-flash:free", self._call_openrouter),
            ("openrouter", self._key_for("openrouter", "OPENROUTER_API_KEY_2"), "google/gemini-2.5-flash:free", self._call_openrouter),
        ]
        if self.mode != "auto":
            chain = [c for c in chain if c[0] == self.mode] or chain
        return chain

    def _call_gemini(self, key, model, prompt):
        import requests
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT_JARVIS}]},
            "contents": [{"parts": [{"text": prompt}]}]
        }
        res = requests.post(url, json=payload, timeout=10, verify=False)
        if res.status_code >= 400:
            raise Exception(f"HTTP {res.status_code}")
        return res.json()["candidates"][0]["content"]["parts"][0]["text"]

    def _call_groq(self, key, model, prompt):
        import requests
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_JARVIS},
            {"role": "user", "content": prompt}
        ]}
        res = requests.post(url, json=payload, headers=headers, timeout=10, verify=False)
        if res.status_code >= 400:
            raise Exception(f"HTTP {res.status_code}")
        return res.json()["choices"][0]["message"]["content"]

    def _call_openrouter(self, key, model, prompt):
        import requests
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_JARVIS},
            {"role": "user", "content": prompt}
        ]}
        res = requests.post(url, json=payload, headers=headers, timeout=10, verify=False)
        if res.status_code >= 400:
            raise Exception(f"HTTP {res.status_code}")
        return res.json()["choices"][0]["message"]["content"]

    def ask(self, prompt):
        """Returns (reply_text_or_None, fail_count_before_success)."""
        chain = self._build_chain()
        fail_count = 0

        for provider, key, model, call_fn in chain:
            if not key:
                fail_count += 1
                continue
            try:
                reply = call_fn(key, model, prompt)
                return strip_think_tags(reply), fail_count
            except Exception:
                fail_count += 1
                continue

        return None, fail_count
