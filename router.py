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

# Auth/plan-level errors: retrying the SAME key with a different model
# will fail identically, so skip straight to the next key.
SKIP_STATUS = {400, 401, 402, 404}
# Transient/overload errors: worth trying a different model on the SAME
# key once before giving up on it (no artificial delay -- keeps the
# fallback fast).
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def strip_think_tags(text):
    if not text:
        return text
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"</?think>", "", cleaned, flags=re.IGNORECASE).strip()


class ProviderHttpError(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__(f"HTTP {status}")


class SmartAIRouter:
    """Fallback order: Gemini -> OpenRouter -> Groq.
    Each provider entry lists 1-2 keys and 1-2 candidate models. Within a
    key, SKIP_STATUS errors abort that key immediately (move to next key);
    RETRYABLE_STATUS errors try the key's next model before moving on.
    DeepSeek is NOT a separately configured provider -- it is only ever
    reachable as an OpenRouter model id, since no DEEPSEEK_API_KEY secret
    exists in this project."""

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
            {"provider": "gemini", "key": self._key_for("gemini", "GEMINI_API_KEY_1"),
             "models": ["gemini-2.5-flash"], "call": self._call_gemini},
            {"provider": "gemini", "key": self._key_for("gemini", "GEMINI_API_KEY_2"),
             "models": ["gemini-2.5-flash"], "call": self._call_gemini},
            {"provider": "openrouter", "key": self._key_for("openrouter", "OPENROUTER_API_KEY_1"),
             "models": ["google/gemini-2.5-flash:free", "meta-llama/llama-3.3-70b-instruct:free"],
             "call": self._call_openrouter},
            {"provider": "openrouter", "key": self._key_for("openrouter", "OPENROUTER_API_KEY_2"),
             "models": ["meta-llama/llama-3.3-70b-instruct:free", "google/gemini-2.5-flash:free"],
             "call": self._call_openrouter},
            {"provider": "groq", "key": self._key_for("groq", "GROQ_API_KEY_1"),
             "models": ["llama3-8b-8192"], "call": self._call_groq},
            {"provider": "groq", "key": self._key_for("groq", "GROQ_API_KEY_2"),
             "models": ["llama3-8b-8192"], "call": self._call_groq},
        ]
        if self.mode != "auto":
            chain = [c for c in chain if c["provider"] == self.mode] or chain
        return chain

    def _to_messages(self, prompt, context):
        messages = [{"role": "system", "content": SYSTEM_PROMPT_JARVIS}]
        for role, content in (context or []):
            messages.append({"role": "user" if role == "user" else "assistant", "content": content})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _requests_kwargs(self):
        import certifi
        # Real fix (not verify=False): point requests at certifi's CA
        # bundle explicitly, since some Android builds don't reliably
        # expose the OS trust store to Python's ssl module.
        return {"timeout": 10, "verify": certifi.where()}

    def _call_gemini(self, key, model, prompt, context):
        import requests
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT_JARVIS}]},
            "contents": [{"parts": [{"text": prompt}]}]
        }
        res = requests.post(url, json=payload, **self._requests_kwargs())
        if res.status_code >= 400:
            raise ProviderHttpError(res.status_code)
        return res.json()["candidates"][0]["content"]["parts"][0]["text"]

    def _call_groq(self, key, model, prompt, context):
        import requests
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": self._to_messages(prompt, context)}
        res = requests.post(url, json=payload, headers=headers, **self._requests_kwargs())
        if res.status_code >= 400:
            raise ProviderHttpError(res.status_code)
        return res.json()["choices"][0]["message"]["content"]

    def _call_openrouter(self, key, model, prompt, context):
        import requests
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": self._to_messages(prompt, context)}
        res = requests.post(url, json=payload, headers=headers, **self._requests_kwargs())
        if res.status_code >= 400:
            raise ProviderHttpError(res.status_code)
        return res.json()["choices"][0]["message"]["content"]

    def ask(self, prompt, context=None):
        """Returns (reply_or_None, fail_count)."""
        chain = self._build_chain()
        fail_count = 0

        for entry in chain:
            key = entry["key"]
            if not key:
                fail_count += 1
                continue

            for model in entry["models"]:
                try:
                    reply = entry["call"](key, model, prompt, context)
                    return strip_think_tags(reply), fail_count
                except ProviderHttpError as e:
                    fail_count += 1
                    if e.status in SKIP_STATUS:
                        break  # this key is bad -- don't try its other models
                    if e.status in RETRYABLE_STATUS:
                        continue  # try this key's next model
                    break
                except Exception:
                    # network/timeout/parse error -- no point trying
                    # another model on the same key right now
                    fail_count += 1
                    break

        return None, fail_count
