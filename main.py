import os
import re
import json
import threading
import time
import traceback
import sqlite3
from datetime import datetime
from kivy import platform
from kivy.app import App
from kivy.metrics import dp
from kivy.core.window import Window
from kivy.animation import Animation
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.switch import Switch
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.image import Image
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.widget import Widget
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.core.text import LabelBase

Window.softinput_mode = 'below_target'

APP_PASS = "01062013"
SETTINGS_PASS = "18112023"
PACKAGE_NAME = "com.jarvis.assistant"
DB_PATH = "jarvis_local.db"
APP_KEYS_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_keys.json")

BG_DARK = (0.051, 0.027, 0.106, 1)
BG_PANEL = (0.071, 0.035, 0.141, 1)
ACCENT_PURPLE = (0.42, 0.15, 0.85, 1)

# ---------------- Jarvis persona system prompt (sent to every AI call) ----------------
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


# ---------------- Devanagari font ----------------
DEVANAGARI_FONT_NAME = "DevanagariFont"
_CANDIDATE_FONT_PATHS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "NotoSansDevanagari-Regular.ttf"),
    "assets/NotoSansDevanagari-Regular.ttf",
    "/system/fonts/NotoSansDevanagari-Regular.ttf",
]
_font_registered = False
for _path in _CANDIDATE_FONT_PATHS:
    if os.path.exists(_path):
        try:
            LabelBase.register(name=DEVANAGARI_FONT_NAME, fn_regular=_path)
            _font_registered = True
            break
        except Exception:
            pass


def app_font():
    return DEVANAGARI_FONT_NAME if _font_registered else "Roboto"


# ---------------- Key loading ----------------
_APP_KEYS_JSON = {}
try:
    if os.path.exists(APP_KEYS_JSON_PATH):
        with open(APP_KEYS_JSON_PATH, "r", encoding="utf-8") as f:
            _APP_KEYS_JSON = json.load(f)
except Exception:
    _APP_KEYS_JSON = {}

_PROVIDER_PREFIX_MAP = {"GROQ": "groq", "GEMINI": "gemini", "OPENROUTER": "openrouter", "CEREBRAS": "cerebras"}


def _lookup_sqlite_override(secret_name):
    provider = None
    for prefix, provider_name in _PROVIDER_PREFIX_MAP.items():
        if secret_name.startswith(prefix):
            provider = provider_name
            break
    if not provider:
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT api_key FROM api_overrides WHERE provider = ?", (provider,))
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return None


def load_key(name):
    val = _APP_KEYS_JSON.get(name)
    if val:
        return val
    val = _lookup_sqlite_override(name)
    if val:
        return val
    return os.environ.get(name)


def show_toast(message):
    if platform != "android":
        return
    try:
        from jnius import autoclass
        Toast = autoclass("android.widget.Toast")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        String = autoclass("java.lang.String")
        activity = PythonActivity.mActivity

        def _show():
            Toast.makeText(activity, String(message), Toast.LENGTH_LONG).show()

        activity.runOnUiThread(_show)
    except Exception:
        pass


# ---------------- Database ----------------
class DatabaseManager:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        cur = self.conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, synced INTEGER DEFAULT 0)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS api_overrides (
            provider TEXT PRIMARY KEY, api_key TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        self.conn.commit()

    def add_note(self, content):
        cur = self.conn.cursor()
        cur.execute("INSERT INTO notes (content) VALUES (?)", (content,))
        self.conn.commit()

    def save_override(self, provider, key):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO api_overrides (provider, api_key, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(provider) DO UPDATE SET api_key=excluded.api_key, updated_at=excluded.updated_at",
            (provider, key, datetime.now().isoformat())
        )
        self.conn.commit()

    def load_overrides(self):
        cur = self.conn.cursor()
        cur.execute("SELECT provider, api_key FROM api_overrides")
        return {row[0]: row[1] for row in cur.fetchall()}


# ---------------- Smart AI Router ----------------
class SmartAIRouter:
    SKIP_STATUS_CODES = {400, 401, 402, 404}

    def __init__(self):
        self.mode = "auto"
        self.providers = [
            {"name": "gemini", "keys": [load_key("GEMINI_API_KEY_1"), load_key("GEMINI_API_KEY_2")],
             "models": ["gemini-2.5-flash", "gemini-3.6-flash"], "call": self._call_gemini},
            {"name": "groq", "keys": [load_key("GROQ_API_KEY_1"), load_key("GROQ_API_KEY_2")],
             "models": ["qwen/qwen3.6-27b", "openai/gpt-oss-120b"], "call": self._call_groq},
            {"name": "openrouter", "keys": [load_key("OPENROUTER_API_KEY_1"), load_key("OPENROUTER_API_KEY_2")],
             "models": ["google/gemini-2.5-flash:free", "meta-llama/llama-3.3-70b-instruct:free"], "call": self._call_openrouter},
            {"name": "cerebras", "keys": [load_key("CEREBRAS_API_KEY_1"), load_key("CEREBRAS_API_KEY_2")],
             "models": ["qwen-3.8-27b", "gemma-4-31b"], "call": self._call_cerebras},
        ]

    def set_mode(self, mode):
        self.mode = mode

    def set_manual_key(self, provider_name, key):
        for p in self.providers:
            if p["name"] == provider_name:
                p["keys"].insert(0, key)
                return True
        return False

    def load_persisted_keys(self, overrides: dict):
        for provider_name, key in overrides.items():
            self.set_manual_key(provider_name, key)

    def _status_of(self, res):
        try:
            return res.status_code
        except Exception:
            return None

    def _call_gemini(self, key, model, prompt):
        import requests
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT_JARVIS}]},
            "contents": [{"parts": [{"text": prompt}]}]
        }
        res = requests.post(url, json=payload, timeout=10, verify=False)
        return res, (lambda r: r.json()["candidates"][0]["content"]["parts"][0]["text"])

    def _call_groq(self, key, model, prompt):
        import requests
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_JARVIS},
            {"role": "user", "content": prompt}
        ]}
        res = requests.post(url, json=payload, headers=headers, timeout=10, verify=False)
        return res, (lambda r: r.json()["choices"][0]["message"]["content"])

    def _call_openrouter(self, key, model, prompt):
        import requests
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_JARVIS},
            {"role": "user", "content": prompt}
        ]}
        res = requests.post(url, json=payload, headers=headers, timeout=10, verify=False)
        return res, (lambda r: r.json()["choices"][0]["message"]["content"])

    def _call_cerebras(self, key, model, prompt):
        import requests
        url = "https://api.cerebras.ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_JARVIS},
            {"role": "user", "content": prompt}
        ]}
        res = requests.post(url, json=payload, headers=headers, timeout=10, verify=False)
        return res, (lambda r: r.json()["choices"][0]["message"]["content"])

    def ask(self, prompt):
        order = self.providers
        if self.mode != "auto":
            order = [p for p in self.providers if p["name"] == self.mode] or self.providers

        errors = []
        tried_any_key = False

        for provider in order:
            keys = [k for k in provider["keys"] if k]
            if not keys:
                errors.append(f"{provider['name']}: कोई API key सेट नहीं है")
                continue
            tried_any_key = True
            for key in keys:
                for model in provider["models"]:
                    try:
                        res, extractor = provider["call"](key, model, prompt)
                    except Exception as e:
                        errors.append(f"{provider['name']}/{model}: {str(e)}")
                        continue
                    status = self._status_of(res)
                    if status and status >= 400:
                        errors.append(f"{provider['name']}/{model}: HTTP {status}")
                        continue
                    try:
                        return strip_think_tags(extractor(res))
                    except Exception as e:
                        errors.append(f"{provider['name']}/{model}: parse error {str(e)}")
                        continue

        if not tried_any_key:
            show_toast("Jarvis: कोई भी API key सेट नहीं है")
            return "ERROR:किसी भी provider की API key नहीं मिली।\n" + "\n".join(errors)

        show_toast("Jarvis: सभी AI providers विफल रहे")
        return "ERROR:सभी providers विफल रहे —\n" + "\n".join(errors)


# ---------------- OneDrive ----------------
class OneDriveClient:
    def __init__(self):
        self.client_id = load_key("ONEDRIVE_CLIENT_ID")
        self.client_secret = load_key("ONEDRIVE_CLIENT_SECRET")
        self.refresh_token = load_key("ONEDRIVE_REFRESH_TOKEN")
        self.access_token = None
        self.last_sync_time = None

    def is_configured(self):
        return bool(self.client_id and self.client_secret and self.refresh_token)

    def get_access_token(self):
        import requests
        if not self.is_configured():
            return None
        url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        data = {"client_id": self.client_id, "client_secret": self.client_secret,
                "refresh_token": self.refresh_token, "grant_type": "refresh_token",
                "scope": "Files.ReadWrite offline_access"}
        try:
            res = requests.post(url, data=data, timeout=10, verify=False)
            res.raise_for_status()
            self.access_token = res.json().get("access_token")
            return self.access_token
        except Exception:
            return None

    def upload_file(self, local_path, remote_name):
        import requests
        token = self.access_token or self.get_access_token()
        if not token:
            return False
        url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{remote_name}:/content"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            with open(local_path, "rb") as f:
                res = requests.put(url, headers=headers, data=f, timeout=20, verify=False)
            if res.status_code in (200, 201):
                self.last_sync_time = datetime.now().strftime("%d-%m-%Y %H:%M")
                return True
            return False
        except Exception:
            return False


# ---------------- Media search ----------------
class MediaSearch:
    def __init__(self):
        self.pexels_key = load_key("PEXELS_API_KEY")
        self.pixabay_key = load_key("PIXABAY_API_KEY")

    def search_pexels(self, query):
        import requests
        if not self.pexels_key:
            return []
        headers = {"Authorization": self.pexels_key}
        try:
            res = requests.get(f"https://api.pexels.com/v1/search?query={query}&per_page=5",
                                headers=headers, timeout=8, verify=False)
            res.raise_for_status()
            return [p["src"]["medium"] for p in res.json().get("photos", [])]
        except Exception:
            return []

    def search_pixabay(self, query):
        import requests
        if not self.pixabay_key:
            return []
        try:
            res = requests.get(f"https://pixabay.com/api/?key={self.pixabay_key}&q={query}&per_page=5",
                                timeout=8, verify=False)
            res.raise_for_status()
            return [h["webformatURL"] for h in res.json().get("hits", [])]
        except Exception:
            return []


# ---------------- Android native TTS ----------------
class AndroidTTS:
    def __init__(self):
        self.engine = None
        self.ready = False
        self.muted = False
        if platform == "android":
            try:
                from jnius import autoclass, PythonJavaClass, java_method
                TextToSpeech = autoclass("android.speech.tts.TextToSpeech")
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                Locale = autoclass("java.util.Locale")

                class Listener(PythonJavaClass):
                    __javainterfaces__ = ["android/speech/tts/TextToSpeech$OnInitListener"]
                    __javacontext__ = "app"

                    def __init__(self, outer):
                        super().__init__()
                        self.outer = outer

                    @java_method("(I)V")
                    def onInit(self, status):
                        if status == 0:
                            try:
                                self.outer.engine.setLanguage(Locale("hi", "IN"))
                            except Exception:
                                pass
                            self.outer.ready = True

                self._listener = Listener(self)
                self.engine = TextToSpeech(PythonActivity.mActivity, self._listener)
            except Exception:
                self.engine = None

    def speak(self, text):
        if self.muted:
            return
        if platform == "android" and self.engine and self.ready:
            try:
                from jnius import autoclass
                TextToSpeech = autoclass("android.speech.tts.TextToSpeech")
                self.engine.speak(text, TextToSpeech.QUEUE_FLUSH, None, None)
            except Exception:
                pass


# ---------------- Wake-word listener (foreground only) ----------------
class WakeWordListener:
    def __init__(self, on_wake):
        self.on_wake = on_wake
        self.enabled = False
        self._thread = None

    def start(self):
        if self.enabled:
            return
        self.enabled = True
        if platform != "android":
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.enabled = False

    def _loop(self):
        try:
            from jnius import autoclass, PythonJavaClass, java_method
            SpeechRecognizer = autoclass("android.speech.SpeechRecognizer")
            RecognizerIntent = autoclass("android.speech.RecognizerIntent")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            activity = PythonActivity.mActivity

            class RecognitionListener(PythonJavaClass):
                __javainterfaces__ = ["android/speech/RecognitionListener"]
                __javacontext__ = "app"

                def __init__(self, outer):
                    super().__init__()
                    self.outer = outer

                @java_method("(Landroid/os/Bundle;)V")
                def onResults(self, results):
                    try:
                        matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        if matches and matches.size() > 0:
                            text = matches.get(0)
                            if text and "jarvis" in text.lower():
                                Clock.schedule_once(lambda dt: self.outer.on_wake())
                    except Exception:
                        pass

                @java_method("(I)V")
                def onError(self, error):
                    pass

                @java_method("(Landroid/os/Bundle;)V")
                def onReadyForSpeech(self, params):
                    pass

                @java_method("(F)V")
                def onRmsChanged(self, rmsdB):
                    pass

                @java_method("([B)V")
                def onBufferReceived(self, buffer):
                    pass

                @java_method("()V")
                def onBeginningOfSpeech(self):
                    pass

                @java_method("()V")
                def onEndOfSpeech(self):
                    pass

                @java_method("(Landroid/os/Bundle;)V")
                def onPartialResults(self, partialResults):
                    pass

                @java_method("(ILandroid/os/Bundle;)V")
                def onEvent(self, eventType, params):
                    pass

            listener = RecognitionListener(self)
            recognizer = SpeechRecognizer.createSpeechRecognizer(activity)
            recognizer.setRecognitionListener(listener)

            intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "hi-IN")

            while self.enabled:
                try:
                    activity.runOnUiThread(lambda: recognizer.startListening(intent))
                except Exception:
                    pass
                time.sleep(4)
        except Exception:
            self.enabled = False


# ---------------- Android settings-intent helper ----------------
def open_android_settings(action, use_package_uri=False):
    if platform != "android":
        return False, "Desktop mode: यह सिर्फ़ Android डिवाइस पर काम करता है।"
    try:
        from jnius import autoclass
        Intent = autoclass("android.content.Intent")
        Settings = autoclass("android.provider.Settings")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity

        action_value = getattr(Settings, action)
        intent = Intent(action_value)

        if use_package_uri:
            Uri = autoclass("android.net.Uri")
            uri = Uri.fromParts("package", PACKAGE_NAME, None)
            intent.setData(uri)

        activity.startActivity(intent)
        return True, "खोला जा रहा है..."
    except Exception as e:
        return False, f"Error: {str(e)}"


# ---------------- Simple app-launch commands (no AI call, no raw links) ----------------
APP_LAUNCH_MAP = {
    "youtube": ("com.google.android.youtube", "YouTube"),
    "यूट्यूब": ("com.google.android.youtube", "YouTube"),
    "notes": ("com.google.android.keep", "Notes"),
    "नोट्स ऐप": ("com.google.android.keep", "Notes"),
    "whatsapp": ("com.whatsapp", "WhatsApp"),
    "व्हाट्सएप": ("com.whatsapp", "WhatsApp"),
}


def try_launch_app(text):
    """Returns a short confirmation string if text matched a known app-open
    command and (on Android) launches it; otherwise returns None so the
    caller falls back to the AI router."""
    cmd = text.lower()
    for keyword, (package, display_name) in APP_LAUNCH_MAP.items():
        if keyword in cmd and ("खोलो" in cmd or "open" in cmd or "kholo" in cmd):
            if platform == "android":
                try:
                    from jnius import autoclass
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    activity = PythonActivity.mActivity
                    pm = activity.getPackageManager()
                    launch_intent = pm.getLaunchIntentForPackage(package)
                    if launch_intent:
                        activity.startActivity(launch_intent)
                        return f"{display_name} खोल रहा हूँ।"
                    return f"{display_name} इस डिवाइस पर इंस्टॉल नहीं है।"
                except Exception as e:
                    return f"{display_name} खोलने में समस्या: {str(e)}"
            return f"{display_name} खोल रहा हूँ। (Desktop mode: सिर्फ़ Android पर काम करता है)"
    return None


# ---------------- Login Screen ----------------
class LoginScreen(Screen):
    def __init__(self, expected_pass, on_success, **kwargs):
        super().__init__(**kwargs)
        self.expected_pass = expected_pass
        self.on_success = on_success
        self.entered = ""

        root = BoxLayout(orientation='vertical')

        top_card = BoxLayout(orientation='vertical', size_hint=(1, 0.42),
                              padding=[20, 40, 20, 20], spacing=20)
        with top_card.canvas.before:
            Color(1, 1, 1, 1)
            self._top_rect = Rectangle(pos=top_card.pos, size=top_card.size)
        top_card.bind(pos=self._sync_rect, size=self._sync_rect)

        self.title_label = Label(text="Jarvis AI\nEnter Password to Access", font_name=app_font(),
                                  color=(0.4, 0.1, 0.8, 1), font_size='22sp', size_hint=(1, 0.5), halign='center')
        self.title_label.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        top_card.add_widget(self.title_label)

        self.pin_display = Label(text="", font_size='30sp', color=(0.4, 0.1, 0.8, 1), size_hint=(1, 0.3))
        top_card.add_widget(self.pin_display)

        self.login_btn = Button(text="Enter", size_hint=(1, 0.2), background_color=(0.55, 0.15, 0.9, 1), font_size='18sp')
        self.login_btn.bind(on_release=self.try_login)
        top_card.add_widget(self.login_btn)
        root.add_widget(top_card)

        keypad_wrap = BoxLayout(orientation='vertical', size_hint=(1, 0.58))
        with keypad_wrap.canvas.before:
            Color(0.55, 0.15, 0.9, 1)
            self._pad_rect = Rectangle(pos=keypad_wrap.pos, size=keypad_wrap.size)
        keypad_wrap.bind(pos=self._sync_pad_rect, size=self._sync_pad_rect)

        grid = GridLayout(cols=3, spacing=15, padding=30)
        keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', 'DEL']
        for k in keys:
            if k == '':
                grid.add_widget(Label(text=''))
                continue
            btn = Button(text=k, font_size='24sp', background_color=(0.65, 0.35, 0.95, 1), background_normal='')
            btn.bind(on_release=self.on_key)
            grid.add_widget(btn)
        keypad_wrap.add_widget(grid)
        root.add_widget(keypad_wrap)
        self.add_widget(root)

    def _sync_rect(self, instance, value):
        self._top_rect.pos = instance.pos
        self._top_rect.size = instance.size

    def _sync_pad_rect(self, instance, value):
        self._pad_rect.pos = instance.pos
        self._pad_rect.size = instance.size

    def on_key(self, instance):
        if instance.text == 'DEL':
            self.entered = self.entered[:-1]
        else:
            self.entered += instance.text
        self.pin_display.text = '•' * len(self.entered)

    def try_login(self, instance):
        if self.entered == self.expected_pass:
            self.on_success()
        else:
            self.pin_display.text = "गलत पासवर्ड"
            self.entered = ""
            Clock.schedule_once(lambda dt: setattr(self.pin_display, 'text', ''), 1.2)


# ---------------- Orb image button ----------------
class OrbButton(ButtonBehavior, Image):
    def __init__(self, on_tap, **kwargs):
        super().__init__(source='assets/orb.png', allow_stretch=True, keep_ratio=True, **kwargs)
        self._on_tap = on_tap

    def on_press(self):
        if self._on_tap:
            self._on_tap()


# ---------------- Quick command icon ----------------
class QuickIconButton(ButtonBehavior, BoxLayout):
    def __init__(self, label_text, on_tap, **kwargs):
        super().__init__(orientation='vertical', **kwargs)
        self._on_tap = on_tap
        with self.canvas.before:
            Color(*BG_PANEL)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[16])
        self.bind(pos=self._sync, size=self._sync)

        lbl = Label(text=label_text, font_name=app_font(), color=(0.9, 0.82, 1, 1),
                    font_size='13sp', halign='center', valign='middle')
        lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        self.add_widget(lbl)

    def _sync(self, instance, value):
        self._bg.pos = instance.pos
        self._bg.size = instance.size

    def on_press(self):
        if self._on_tap:
            self._on_tap()


# ---------------- Main Screen ----------------
class MainScreen(Screen):
    DRAWER_WIDTH = dp(260)

    def __init__(self, on_settings, **kwargs):
        super().__init__(**kwargs)
        self.db = DatabaseManager()
        self.router = SmartAIRouter()
        self.router.load_persisted_keys(self.db.load_overrides())
        self.onedrive = OneDriveClient()
        self.media = MediaSearch()
        self.tts = AndroidTTS()
        self.wake_listener = WakeWordListener(on_wake=self.trigger_voice_listening)
        self.on_settings = on_settings
        self.drawer_open = False

        outer = FloatLayout()

        content = BoxLayout(orientation='vertical', size_hint=(1, 1))
        with content.canvas.before:
            Color(*BG_DARK)
            self._bg = Rectangle(pos=content.pos, size=content.size)
        content.bind(pos=self._sync_bg, size=self._sync_bg)

        header = BoxLayout(orientation='horizontal', size_hint=(1, None), height=60, padding=[15, 5, 15, 5])
        menu_btn = Button(text="=", font_size='22sp', size_hint=(None, 1), width=50,
                           background_color=(0, 0, 0, 0), background_normal='', color=(1, 1, 1, 1))
        menu_btn.bind(on_release=lambda inst: self.toggle_drawer())
        header.add_widget(menu_btn)

        title = Label(text="[b]JARVIS[/b] [color=#b06bffff]AI[/color]", markup=True,
                      font_size='24sp', color=(1, 1, 1, 1))
        header.add_widget(title)

        settings_btn = Button(text="⚙", font_size='20sp', size_hint=(None, 1), width=50,
                               background_color=(0, 0, 0, 0), background_normal='', color=ACCENT_PURPLE)
        settings_btn.bind(on_release=lambda inst: self.on_settings())
        header.add_widget(settings_btn)
        content.add_widget(header)

        # extra top padding so subtitle clears the header
        content.add_widget(Widget(size_hint=(1, None), height=dp(10)))

        subtitle = Label(text="YOUR INTELLIGENT VOICE ASSISTANT", font_size='12sp',
                          color=(0.6, 0.5, 0.75, 1), size_hint=(1, None), height=30)
        content.add_widget(subtitle)

        content.add_widget(Widget(size_hint=(1, None), height=dp(20)))

        # Glow orb container now ~42% of screen height
        orb_wrap = AnchorLayout(size_hint=(1, 0.42))
        orb_btn = OrbButton(on_tap=self.trigger_voice_listening, size_hint=(0.94, 1))
        orb_wrap.add_widget(orb_btn)
        content.add_widget(orb_wrap)

        icons_grid = GridLayout(cols=5, rows=1, size_hint=(1, 0.12), spacing=8, padding=[10, 8, 10, 8])
        quick_actions = [
            ("नोट्स", "नोट लो"),
            ("अलार्म", "अलार्म सेट करो"),
            ("म्यूजिक", "गाना बजाओ"),
            ("टॉर्च", "टॉर्च ऑन करो"),
            ("वाई-फाई", "वाई-फाई टॉगल करो"),
        ]
        for label_text, command_text in quick_actions:
            btn = QuickIconButton(label_text=label_text, on_tap=lambda ct=command_text: self.process_command(ct))
            icons_grid.add_widget(btn)
        content.add_widget(icons_grid)

        self.chat_scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        self.chat_display = Label(text="", markup=True, font_name=app_font(), color=(1, 1, 1, 1), font_size='14sp',
                                   size_hint=(1, None), halign='left', valign='top', padding=[15, 10])
        self.chat_display.bind(
            width=lambda inst, val: setattr(inst, 'text_size', (val, None)),
            texture_size=self._on_chat_texture_size
        )
        self.chat_scroll.add_widget(self.chat_display)
        content.add_widget(self.chat_scroll)

        # ---- Capsule chat bar with mic icon ----
        input_bar = BoxLayout(orientation='horizontal', size_hint=(1, None), height=dp(54),
                               padding=[16, 4, 6, 4], spacing=8)
        with input_bar.canvas.before:
            Color(*BG_PANEL)
            self._input_bar_bg = RoundedRectangle(pos=input_bar.pos, size=input_bar.size, radius=[dp(27)])
        input_bar.bind(pos=self._sync_input_bar, size=self._sync_input_bar)

        self.chat_input = TextInput(
            hint_text="टाइप करें या 'set api gemini KEY' भेजें",
            multiline=False,
            size_hint=(1, 1),
            background_color=(0, 0, 0, 0),
            foreground_color=(1, 1, 1, 1),
            hint_text_color=(0.6, 0.5, 0.7, 1),
            cursor_color=ACCENT_PURPLE,
            padding=[12, 14, 12, 12]
        )
        self.chat_input.bind(on_text_validate=self.on_send)
        input_bar.add_widget(self.chat_input)

        send_btn = Button(text="Send", size_hint=(None, 1), width=70,
                           background_color=ACCENT_PURPLE, background_normal='')
        send_btn.bind(on_release=self.on_send)
        input_bar.add_widget(send_btn)

        mic_btn = Button(text="\U0001F3A4", font_size='18sp', size_hint=(None, 1), width=dp(44),
                          background_color=ACCENT_PURPLE, background_normal='')
        mic_btn.bind(on_release=lambda inst: self.trigger_voice_listening())
        input_bar.add_widget(mic_btn)

        content.add_widget(input_bar)
        outer.add_widget(content)

        self.drawer = BoxLayout(orientation='vertical', size_hint=(None, 1),
                                 width=self.DRAWER_WIDTH, x=-self.DRAWER_WIDTH,
                                 padding=18, spacing=14)
        with self.drawer.canvas.before:
            Color(*BG_PANEL)
            self._drawer_bg = Rectangle(pos=self.drawer.pos, size=self.drawer.size)
        self.drawer.bind(pos=self._sync_drawer_bg, size=self._sync_drawer_bg)

        drawer_header = BoxLayout(orientation='horizontal', size_hint=(1, None), height=36)
        drawer_title = Label(text="[b]Menu[/b]", markup=True, font_size='18sp', color=(1, 1, 1, 1))
        drawer_header.add_widget(drawer_title)
        close_btn = Button(text="X", size_hint=(None, 1), width=36, font_size='16sp',
                            background_color=(0, 0, 0, 0), background_normal='', color=(1, 1, 1, 1))
        close_btn.bind(on_release=lambda inst: self.toggle_drawer())
        drawer_header.add_widget(close_btn)
        self.drawer.add_widget(drawer_header)

        self.drawer.add_widget(Label(text="Model", font_size='13sp', color=(0.7, 0.6, 0.85, 1),
                                      size_hint=(1, None), height=22, halign='left'))
        model_col = BoxLayout(orientation='vertical', size_hint=(1, None), height=220, spacing=6)
        for mode_name in ["auto", "gemini", "groq", "openrouter", "cerebras"]:
            tb = ToggleButton(text=mode_name.capitalize(), group='model_mode',
                               state='down' if mode_name == 'auto' else 'normal',
                               background_color=ACCENT_PURPLE, size_hint=(1, None), height=38)
            tb.bind(on_release=lambda inst, m=mode_name: self.router.set_mode(m))
            model_col.add_widget(tb)
        self.drawer.add_widget(model_col)

        self.onedrive_status_label = Label(
            text="OneDrive: --", font_size='13sp', color=(0.8, 0.75, 0.9, 1),
            size_hint=(1, None), height=50, halign='left', valign='top'
        )
        self.onedrive_status_label.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        self.drawer.add_widget(self.onedrive_status_label)

        about_scroll = ScrollView(size_hint=(1, 1))
        about_text = (
            "About Jarvis AI\n\n"
            "- Deterministic failover: Gemini -> Groq -> OpenRouter(:free) -> Cerebras\n"
            "- Keys: app_keys.json -> SQLite override -> os.environ\n"
            "- Wake-word + TTS controlled from Settings\n"
            "- Local SQLite notes\n"
            "- OneDrive cloud sync"
        )
        about_lbl = Label(text=about_text, font_size='12sp', color=(0.65, 0.6, 0.75, 1),
                           size_hint=(1, None), halign='left', valign='top')
        about_lbl.bind(
            width=lambda inst, val: setattr(inst, 'text_size', (val, None)),
            texture_size=lambda inst, val: setattr(inst, 'height', val[1])
        )
        about_scroll.add_widget(about_lbl)
        self.drawer.add_widget(about_scroll)

        outer.add_widget(self.drawer)
        self.add_widget(outer)

    def _sync_bg(self, instance, value):
        self._bg.pos = instance.pos
        self._bg.size = instance.size

    def _sync_input_bar(self, instance, value):
        self._input_bar_bg.pos = instance.pos
        self._input_bar_bg.size = instance.size

    def _sync_drawer_bg(self, instance, value):
        self._drawer_bg.pos = instance.pos
        self._drawer_bg.size = instance.size

    def _on_chat_texture_size(self, instance, value):
        instance.height = value[1]
        Clock.schedule_once(lambda dt: setattr(self.chat_scroll, 'scroll_y', 0), 0)

    def toggle_drawer(self):
        target_x = 0 if not self.drawer_open else -self.DRAWER_WIDTH
        Animation(x=target_x, d=0.25, t='out_cubic').start(self.drawer)
        self.drawer_open = not self.drawer_open
        if self.drawer_open:
            self.refresh_onedrive_status()

    def refresh_onedrive_status(self):
        status = "Connected" if self.onedrive.is_configured() else "Not Configured"
        last = self.onedrive.last_sync_time or "कभी नहीं"
        self.onedrive_status_label.text = f"OneDrive: {status}\nLast Sync: {last}"

    def trigger_voice_listening(self):
        self.process_command("हेलो जार्विस, सिस्टम स्टेटस चेक करो")

    def on_send(self, *args):
        text = self.chat_input.text.strip()
        if not text:
            return
        self.chat_input.text = ''
        if text.lower().startswith('set api '):
            self.handle_set_api(text)
        else:
            self.process_command(text)

    def handle_set_api(self, text):
        parts = text.split(maxsplit=3)
        if len(parts) < 4:
            self._append_system_msg("प्रारूप: set api <provider> <key>")
            return
        provider = parts[2].lower()
        key = parts[3]
        ok = self.router.set_manual_key(provider, key)
        if ok:
            self.db.save_override(provider, key)
            self._append_system_msg(f"{provider} API key सेव हो गई (restart के बाद भी रहेगी)।")
        else:
            self._append_system_msg(f"अज्ञात provider: {provider}")

    def _append_system_msg(self, msg):
        self.chat_display.text += f"\n[color=#b06bffff]System:[/color] {msg}\n"

    def process_command(self, text):
        self.chat_display.text += f"\n[color=#4fd1ff]You:[/color] {text}\n"

        app_reply = try_launch_app(text)
        if app_reply:
            self.chat_display.text += f"[color=#b06bffff]Jarvis:[/color] {app_reply}\n"
            self.tts.speak(app_reply)
            return

        self.chat_display.text += "प्रोसेसिंग..."
        threading.Thread(target=self._async_process, args=(text,), daemon=True).start()

    def _async_process(self, text):
        reply = self.router.ask(text)
        self.db.add_note(f"User: {text} | AI: {reply}")
        Clock.schedule_once(lambda dt: self._update_reply(reply))

    def _update_reply(self, reply):
        if self.chat_display.text.endswith("प्रोसेसिंग..."):
            self.chat_display.text = self.chat_display.text[:-len("प्रोसेसिंग...")]

        if reply.startswith("ERROR:"):
            clean = reply[len("ERROR:"):]
            self.chat_display.text += f"\n[color=#ff5c5c]Error:[/color] {clean}\n"
        else:
            self.chat_display.text += f"\n[color=#b06bffff]Jarvis:[/color] {reply}\n"
            self.tts.speak(reply)

    def handle_assist_intent(self, spoken_text):
        if spoken_text:
            self.process_command(spoken_text)


# ---------------- Settings ----------------
class SettingsScreen(Screen):
    def __init__(self, on_back, main_screen_ref, **kwargs):
        super().__init__(**kwargs)
        self.main_screen_ref = main_screen_ref
        root = BoxLayout(orientation='vertical', padding=20, spacing=14)
        with root.canvas.before:
            Color(*BG_DARK)
            self._bg = Rectangle(pos=root.pos, size=root.size)
        root.bind(pos=self._sync_bg, size=self._sync_bg)

        title_lbl = Label(text="Settings", font_name=app_font(), color=(0.8, 0.7, 1, 1),
                           font_size='20sp', size_hint=(1, None), height=40)
        root.add_widget(title_lbl)

        self.status_lbl = Label(text="", font_size='13sp', color=(0.7, 0.9, 0.7, 1),
                                 size_hint=(1, None), height=40, halign='center')
        self.status_lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        root.add_widget(self.status_lbl)

        wake_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=48)
        wake_row.add_widget(Label(text="Wake Word Detection (Jarvis)", font_name=app_font(),
                                   color=(0.85, 0.8, 0.95, 1), font_size='14sp'))
        wake_switch = Switch(active=False)
        wake_switch.bind(active=self._on_wake_toggle)
        wake_row.add_widget(wake_switch)
        root.add_widget(wake_row)

        tts_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=48)
        tts_row.add_widget(Label(text="Mute / Unmute Voice Output", font_name=app_font(),
                                  color=(0.85, 0.8, 0.95, 1), font_size='14sp'))
        tts_switch = Switch(active=False)
        tts_switch.bind(active=self._on_tts_mute_toggle)
        tts_row.add_widget(tts_switch)
        root.add_widget(tts_row)

        voice_btn = Button(text="Set Default Voice Assistant", size_hint=(1, None), height=55,
                            background_color=ACCENT_PURPLE)
        voice_btn.bind(on_release=lambda inst: self._run_intent("ACTION_VOICE_INPUT_SETTINGS", False))
        root.add_widget(voice_btn)

        accessibility_btn = Button(text="Enable Accessibility Service", size_hint=(1, None), height=55,
                                    background_color=ACCENT_PURPLE)
        accessibility_btn.bind(on_release=lambda inst: self._run_intent("ACTION_ACCESSIBILITY_SETTINGS", False))
        root.add_widget(accessibility_btn)

        perms_btn = Button(text="App Permissions (Mic / Overlay / Notifications)", size_hint=(1, None), height=55,
                            background_color=ACCENT_PURPLE)
        perms_btn.bind(on_release=lambda inst: self._run_intent("ACTION_APPLICATION_DETAILS_SETTINGS", True))
        root.add_widget(perms_btn)

        root.add_widget(Widget(size_hint=(1, 1)))

        back_btn = Button(text="Back", size_hint=(1, None), height=50, background_color=BG_PANEL)
        back_btn.bind(on_release=lambda inst: on_back())
        root.add_widget(back_btn)
        self.add_widget(root)

    def _on_wake_toggle(self, instance, value):
        if value:
            self.main_screen_ref.wake_listener.start()
            self.status_lbl.text = "Wake-word सुनना शुरू हुआ (जब तक ऐप खुली है)"
        else:
            self.main_screen_ref.wake_listener.stop()
            self.status_lbl.text = "Wake-word बंद कर दिया गया"

    def _on_tts_mute_toggle(self, instance, value):
        self.main_screen_ref.tts.muted = value
        self.status_lbl.text = "आवाज़ म्यूट कर दी गई" if value else "आवाज़ चालू है"

    def _run_intent(self, action, use_package_uri):
        ok, msg = open_android_settings(action, use_package_uri)
        self.status_lbl.color = (0.7, 0.9, 0.7, 1) if ok else (1, 0.5, 0.5, 1)
        self.status_lbl.text = msg

    def _sync_bg(self, instance, value):
        self._bg.pos = instance.pos
        self._bg.size = instance.size


class ErrorScreen(Screen):
    def __init__(self, error_text, **kwargs):
        super().__init__(**kwargs)
        root = BoxLayout(orientation='vertical', padding=15)
        with root.canvas.before:
            Color(0.1, 0, 0, 1)
            self._bg = Rectangle(pos=root.pos, size=root.size)
        root.bind(pos=self._sync_bg, size=self._sync_bg)

        scroll = ScrollView(size_hint=(1, 1))
        lbl = Label(text="STARTUP ERROR:\n\n" + error_text, color=(1, 0.7, 0.7, 1),
                    font_size='13sp', size_hint=(1, None), halign='left', valign='top')
        lbl.bind(
            width=lambda inst, val: setattr(inst, 'text_size', (val, None)),
            texture_size=lambda inst, val: setattr(inst, 'height', val[1])
        )
        scroll.add_widget(lbl)
        root.add_widget(scroll)
        self.add_widget(root)

    def _sync_bg(self, instance, value):
        self._bg.pos = instance.pos
        self._bg.size = instance.size


class JarvisApp(App):
    def build(self):
        sm = ScreenManager()
        try:
            login = LoginScreen(APP_PASS, on_success=self.go_main, name='login')
            self.main_screen = MainScreen(on_settings=self.go_settings_lock, name='main')
            settings_lock = LoginScreen(SETTINGS_PASS, on_success=self.go_settings, name='settings_lock')
            settings_screen = SettingsScreen(on_back=self.go_main, main_screen_ref=self.main_screen, name='settings')

            sm.add_widget(login)
            sm.add_widget(self.main_screen)
            sm.add_widget(settings_lock)
            sm.add_widget(settings_screen)
        except Exception:
            err_text = traceback.format_exc()
            try:
                with open("jarvis_crash_log.txt", "w") as f:
                    f.write(err_text)
            except Exception:
                pass
            sm.clear_widgets()
            sm.add_widget(ErrorScreen(err_text, name='error'))

        self.sm = sm
        self._check_assist_intent()
        return sm

    def _check_assist_intent(self):
        if platform != "android":
            return
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            intent = activity.getIntent()
            action = intent.getAction() if intent else None
            if action == "android.intent.action.ASSIST":
                extras = intent.getExtras()
                spoken = extras.getString("android.intent.extra.ASSIST_CONTEXT") if extras else None
                Clock.schedule_once(lambda dt: self.main_screen.handle_assist_intent(spoken or "असिस्ट खोला गया"))
        except Exception:
            pass

    def go_main(self):
        self.sm.current = 'main'

    def go_settings_lock(self):
        self.sm.current = 'settings_lock'

    def go_settings(self):
        self.sm.current = 'settings'


if __name__ == "__main__":
    JarvisApp().run()
