import os
import threading
import traceback
from datetime import datetime
from kivy import platform
from kivy.app import App
from kivy.metrics import dp
from kivy.animation import Animation
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.image import Image
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.widget import Widget
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.core.text import LabelBase
import sqlite3

APP_PASS = "01062013"
SETTINGS_PASS = "18112023"

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


# ---------------- Database ----------------
class DatabaseManager:
    def __init__(self):
        self.conn = sqlite3.connect("jarvis_local.db", check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        cur = self.conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, synced INTEGER DEFAULT 0)""")
        self.conn.commit()

    def add_note(self, content):
        cur = self.conn.cursor()
        cur.execute("INSERT INTO notes (content) VALUES (?)", (content,))
        self.conn.commit()


# ---------------- Smart AI Router ----------------
class SmartAIRouter:
    def __init__(self):
        self.mode = "auto"  # 'auto' | 'groq' | 'gemini' | 'openrouter' | 'cerebras'
        self.providers = [
            {"name": "groq", "keys": [os.environ.get("GROQ_API_KEY_1"), os.environ.get("GROQ_API_KEY_2")], "call": self._call_groq},
            {"name": "gemini", "keys": [os.environ.get("GEMINI_API_KEY_1"), os.environ.get("GEMINI_API_KEY_2")], "call": self._call_gemini},
            {"name": "openrouter", "keys": [os.environ.get("OPENROUTER_API_KEY_1"), os.environ.get("OPENROUTER_API_KEY_2")], "call": self._call_openrouter},
            {"name": "cerebras", "keys": [os.environ.get("CEREBRAS_API_KEY_1"), os.environ.get("CEREBRAS_API_KEY_2")], "call": self._call_cerebras},
        ]
        self.key_index = {p["name"]: 0 for p in self.providers}

    def set_mode(self, mode):
        self.mode = mode

    def set_manual_key(self, provider_name, key):
        for p in self.providers:
            if p["name"] == provider_name:
                p["keys"].insert(0, key)
                self.key_index[provider_name] = 0
                return True
        return False

    def _next_key(self, provider):
        keys = [k for k in provider["keys"] if k]
        if not keys:
            return None
        idx = self.key_index[provider["name"]] % len(keys)
        self.key_index[provider["name"]] += 1
        return keys[idx]

    def _call_groq(self, key, prompt):
        import requests
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}]}
        res = requests.post(url, json=payload, headers=headers, timeout=8)
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"]

    def _call_gemini(self, key, prompt):
        import requests
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        res = requests.post(url, json=payload, timeout=8)
        res.raise_for_status()
        return res.json()["candidates"][0]["content"]["parts"][0]["text"]

    def _call_openrouter(self, key, prompt):
        import requests
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": "deepseek/deepseek-r1", "messages": [{"role": "user", "content": prompt}]}
        res = requests.post(url, json=payload, headers=headers, timeout=8)
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"]

    def _call_cerebras(self, key, prompt):
        import requests
        url = "https://api.cerebras.ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": "llama-3.3-70b", "messages": [{"role": "user", "content": prompt}]}
        res = requests.post(url, json=payload, headers=headers, timeout=8)
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"]

    def ask(self, prompt):
        order = self.providers
        if self.mode != "auto":
            order = [p for p in self.providers if p["name"] == self.mode] or self.providers
        for provider in order:
            key = self._next_key(provider)
            if not key:
                continue
            try:
                return provider["call"](key, prompt)
            except Exception:
                continue
        return "ऑफ़लाइन मोड: सभी API राउट विफल रहे।"


# ---------------- OneDrive ----------------
class OneDriveClient:
    def __init__(self):
        self.client_id = os.environ.get("ONEDRIVE_CLIENT_ID")
        self.client_secret = os.environ.get("ONEDRIVE_CLIENT_SECRET")
        self.refresh_token = os.environ.get("ONEDRIVE_REFRESH_TOKEN")
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
            res = requests.post(url, data=data, timeout=10)
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
                res = requests.put(url, headers=headers, data=f, timeout=20)
            if res.status_code in (200, 201):
                self.last_sync_time = datetime.now().strftime("%d-%m-%Y %H:%M")
                return True
            return False
        except Exception:
            return False


# ---------------- Media search ----------------
class MediaSearch:
    def __init__(self):
        self.pexels_key = os.environ.get("PEXELS_API_KEY")
        self.pixabay_key = os.environ.get("PIXABAY_API_KEY")

    def search_pexels(self, query):
        import requests
        if not self.pexels_key:
            return []
        headers = {"Authorization": self.pexels_key}
        try:
            res = requests.get(f"https://api.pexels.com/v1/search?query={query}&per_page=5", headers=headers, timeout=8)
            res.raise_for_status()
            return [p["src"]["medium"] for p in res.json().get("photos", [])]
        except Exception:
            return []

    def search_pixabay(self, query):
        import requests
        if not self.pixabay_key:
            return []
        try:
            res = requests.get(f"https://pixabay.com/api/?key={self.pixabay_key}&q={query}&per_page=5", timeout=8)
            res.raise_for_status()
            return [h["webformatURL"] for h in res.json().get("hits", [])]
        except Exception:
            return []


# ---------------- Android native TTS ----------------
class AndroidTTS:
    def __init__(self):
        self.engine = None
        self.ready = False
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
        if platform == "android" and self.engine and self.ready:
            try:
                from jnius import autoclass
                TextToSpeech = autoclass("android.speech.tts.TextToSpeech")
                self.engine.speak(text, TextToSpeech.QUEUE_FLUSH, None, None)
            except Exception:
                pass


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

        self.login_btn = Button(text="Login", size_hint=(1, 0.2), background_color=(0.55, 0.15, 0.9, 1), font_size='18sp')
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
        from kivy.graphics import RoundedRectangle
        with self.canvas.before:
            Color(0.22, 0.1, 0.35, 1)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[14])
        self.bind(pos=self._sync, size=self._sync)

        lbl = Label(text=label_text, font_name=app_font(), color=(0.85, 0.75, 1, 1),
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
        self.onedrive = OneDriveClient()
        self.media = MediaSearch()
        self.tts = AndroidTTS()
        self.silent_mode = False
        self.on_settings = on_settings
        self.drawer_open = False

        outer = FloatLayout()

        # ---- Main content column ----
        content = BoxLayout(orientation='vertical', size_hint=(1, 1))
        with content.canvas.before:
            Color(0.04, 0.02, 0.08, 1)
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

        settings_btn = Button(text="*", font_size='20sp', size_hint=(None, 1), width=50,
                               background_color=(0, 0, 0, 0), background_normal='', color=(1, 1, 1, 1))
        settings_btn.bind(on_release=lambda inst: self.on_settings())
        header.add_widget(settings_btn)
        content.add_widget(header)

        subtitle = Label(text="YOUR INTELLIGENT VOICE ASSISTANT", font_size='12sp',
                          color=(0.6, 0.5, 0.75, 1), size_hint=(1, None), height=30)
        content.add_widget(subtitle)

        # margin between subtitle and orb
        content.add_widget(Widget(size_hint=(1, None), height=dp(28)))

        orb_wrap = AnchorLayout(size_hint=(1, 0.34))
        orb_btn = OrbButton(on_tap=self.trigger_voice_listening, size_hint=(None, None), size=(dp(190), dp(190)))
        orb_wrap.add_widget(orb_btn)
        content.add_widget(orb_wrap)

        icons_grid = GridLayout(cols=5, rows=1, size_hint=(1, 0.14), spacing=8, padding=[10, 8, 10, 8])
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

        scroll = ScrollView(size_hint=(1, 1))
        self.chat_display = Label(text="", font_name=app_font(), color=(1, 1, 1, 1), font_size='14sp',
                                   size_hint=(1, None), halign='left', valign='top', padding=[15, 10])
        self.chat_display.bind(
            width=lambda inst, val: setattr(inst, 'text_size', (val, None)),
            texture_size=lambda inst, val: setattr(inst, 'height', val[1])
        )
        scroll.add_widget(self.chat_display)
        content.add_widget(scroll)

        # ---- Bottom chat input bar (Gemini-style) ----
        input_bar = BoxLayout(orientation='horizontal', size_hint=(1, None), height=54,
                               padding=[10, 8, 10, 8], spacing=8)
        with input_bar.canvas.before:
            Color(0.12, 0.06, 0.2, 1)
            self._input_bar_bg = Rectangle(pos=input_bar.pos, size=input_bar.size)
        input_bar.bind(pos=self._sync_input_bar, size=self._sync_input_bar)

        self.chat_input = TextInput(
            hint_text="टाइप करें या 'set api gemini KEY' भेजें",
            multiline=False,
            size_hint=(1, 1),
            background_color=(0.2, 0.1, 0.3, 1),
            foreground_color=(1, 1, 1, 1),
            hint_text_color=(0.6, 0.5, 0.7, 1),
            cursor_color=(0.72, 0.45, 1, 1),
            padding=[10, 10, 10, 10]
        )
        self.chat_input.bind(on_text_validate=self.on_send)
        input_bar.add_widget(self.chat_input)

        send_btn = Button(text="Send", size_hint=(None, 1), width=80,
                           background_color=(0.55, 0.15, 0.9, 1), background_normal='')
        send_btn.bind(on_release=self.on_send)
        input_bar.add_widget(send_btn)

        content.add_widget(input_bar)
        outer.add_widget(content)

        # ---- Side drawer (overlay, no Settings item) ----
        self.drawer = BoxLayout(orientation='vertical', size_hint=(None, 1),
                                 width=self.DRAWER_WIDTH, x=-self.DRAWER_WIDTH,
                                 padding=18, spacing=16)
        with self.drawer.canvas.before:
            Color(0.1, 0.04, 0.18, 1)
            self._drawer_bg = Rectangle(pos=self.drawer.pos, size=self.drawer.size)
        self.drawer.bind(pos=self._sync_drawer_bg, size=self._sync_drawer_bg)

        drawer_title = Label(text="[b]Menu[/b]", markup=True, font_size='18sp',
                              color=(1, 1, 1, 1), size_hint=(1, None), height=30)
        self.drawer.add_widget(drawer_title)

        self.drawer.add_widget(Label(text="Model", font_size='13sp', color=(0.7, 0.6, 0.85, 1),
                                      size_hint=(1, None), height=22, halign='left'))
        model_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=40, spacing=6)
        for mode_name in ["auto", "groq", "gemini"]:
            tb = ToggleButton(text=mode_name.capitalize(), group='model_mode',
                               state='down' if mode_name == 'auto' else 'normal',
                               background_color=(0.4, 0.15, 0.7, 1))
            tb.bind(on_release=lambda inst, m=mode_name: self.router.set_mode(m))
            model_row.add_widget(tb)
        self.drawer.add_widget(model_row)

        self.onedrive_status_label = Label(
            text="OneDrive: --", font_size='13sp', color=(0.8, 0.75, 0.9, 1),
            size_hint=(1, None), height=50, halign='left', valign='top'
        )
        self.onedrive_status_label.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        self.drawer.add_widget(self.onedrive_status_label)

        about_scroll = ScrollView(size_hint=(1, 1))
        about_text = (
            "About Jarvis AI\n\n"
            "- Multi-provider AI router (Groq, Gemini, OpenRouter, Cerebras) "
            "with auto key rotation and failover.\n"
            "- Local SQLite note storage.\n"
            "- OneDrive cloud sync (client credentials + refresh token).\n"
            "- Android native TTS (Hindi) for spoken replies.\n"
            "- Type 'set api <provider> <key>' in the chat box to override "
            "a key for this session only."
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
            self._append_system_msg(f"{provider} API key अपडेट हो गई (इस सेशन के लिए)।")
        else:
            self._append_system_msg(f"अज्ञात provider: {provider}")

    def _append_system_msg(self, msg):
        self.chat_display.markup = True
        self.chat_display.text += f"\n[color=#b06bffff]System:[/color] {msg}\n"

    def process_command(self, text):
        self.chat_display.markup = True
        self.chat_display.text += f"\n[color=#b06bffff]You:[/color] {text}\nप्रोसेसिंग..."
        threading.Thread(target=self._async_process, args=(text,), daemon=True).start()

    def _async_process(self, text):
        cmd = text.lower()
        if "म्यूट" in cmd or "silent mode" in cmd:
            self.silent_mode = True
            Clock.schedule_once(lambda dt: self._update_reply("न्यूरल वॉयस म्यूट कर दी गई है।"))
            return
        reply = self.router.ask(text)
        self.db.add_note(f"User: {text} | AI: {reply}")
        Clock.schedule_once(lambda dt: self._update_reply(reply))

    def _update_reply(self, reply):
        prefix = "[UI-Only Mode]" if self.silent_mode else "Jarvis:"
        if self.chat_display.text.endswith("प्रोसेसिंग..."):
            self.chat_display.text = self.chat_display.text[:-len("प्रोसेसिंग...")]
        self.chat_display.text += f"\n{prefix} {reply}\n"
        if not self.silent_mode:
            self.tts.speak(reply)

    def handle_assist_intent(self, spoken_text):
        if spoken_text:
            self.process_command(spoken_text)


# ---------------- Settings (password-protected, from header gear icon only) ----------------
class SettingsScreen(Screen):
    def __init__(self, on_back, **kwargs):
        super().__init__(**kwargs)
        root = BoxLayout(orientation='vertical', padding=20, spacing=20)
        with root.canvas.before:
            Color(0.04, 0.02, 0.08, 1)
            self._bg = Rectangle(pos=root.pos, size=root.size)
        root.bind(pos=self._sync_bg, size=self._sync_bg)

        lbl = Label(text="Settings\n(macros, accessibility config coming next phase)",
                    font_name=app_font(), color=(0.8, 0.7, 1, 1), font_size='16sp', halign='center')
        lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        root.add_widget(lbl)

        back_btn = Button(text="Back", size_hint=(1, None), height=50, background_color=(0.55, 0.15, 0.9, 1))
        back_btn.bind(on_release=lambda inst: on_back())
        root.add_widget(back_btn)
        self.add_widget(root)

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
            settings_screen = SettingsScreen(on_back=self.go_main, name='settings')

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
