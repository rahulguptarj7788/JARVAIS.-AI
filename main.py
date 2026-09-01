import os
import sqlite3
import threading
from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.clock import Clock
from kivy.graphics import Color, Ellipse
from kivy.core.text import LabelBase

APP_PASS = "01062013"
SETTINGS_PASS = "18112023"

# ---------- Devanagari font support ----------
# Kivy's default font has no Hindi glyphs. Many Android devices ship a
# Devanagari-capable system font. Try common paths and register the first
# one that exists. If none exist, fall back silently to the default font
# (Hindi text will still show boxes on that device, but the app won't crash).
DEVANAGARI_FONT_NAME = "DevanagariFont"
_CANDIDATE_FONT_PATHS = [
    "/system/fonts/NotoSansDevanagari-Regular.ttf",
    "/system/fonts/NotoSansDevanagariUI-Regular.ttf",
    "/system/fonts/NotoSansDevanagari.ttf",
    "/system/fonts/MiSansDevanagari-Regular.ttf",
    "/system/fonts/Hind-Regular.ttf",
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
    return DEVANAGARI_FONT_NAME if _font_registered else None


class DatabaseManager:
    def __init__(self):
        self.conn = sqlite3.connect("jarvis_local.db", check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                synced INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS macros (
                action_name TEXT PRIMARY KEY,
                json_steps TEXT
            )
        """)
        self.conn.commit()

    def add_note(self, content):
        cur = self.conn.cursor()
        cur.execute("INSERT INTO notes (content) VALUES (?)", (content,))
        self.conn.commit()


class SmartAIRouter:
    def __init__(self):
        self.groq_keys = [os.environ.get("GROQ_API_KEY_1"), os.environ.get("GROQ_API_KEY_2")]
        self.active_index = 0

    def query_groq(self, prompt):
        import requests
        keys = [k for k in self.groq_keys if k]
        if not keys:
            return None
        key = keys[self.active_index % len(keys)]
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}]
        }
        try:
            res = requests.post(url, json=payload, timeout=8)
            if res.status_code == 200:
                return res.json()["choices"][0]["message"]["content"]
        except Exception:
            self.active_index += 1
        return None

    def ask(self, prompt):
        res = self.query_groq(prompt)
        if res:
            return res
        return "ऑफ़लाइन मोड: लोकल मैक्रो एवं कैलकुलेशन इंजन एक्टिव है।"


# ---------- Login Screen (PIN keypad UI) ----------
class LoginScreen(Screen):
    def __init__(self, expected_pass, on_success, **kwargs):
        super().__init__(**kwargs)
        self.expected_pass = expected_pass
        self.on_success = on_success
        self.entered = ""

        root = BoxLayout(orientation='vertical')

        # Top white card area
        top_card = BoxLayout(orientation='vertical', size_hint=(1, 0.42),
                              padding=[20, 40, 20, 20], spacing=20)
        with top_card.canvas.before:
            Color(1, 1, 1, 1)
            self._top_bg = Ellipse  # placeholder, real rect drawn below
        from kivy.graphics import Rectangle
        with top_card.canvas.before:
            Color(1, 1, 1, 1)
            self._top_rect = Rectangle(pos=top_card.pos, size=top_card.size)
        top_card.bind(pos=self._sync_rect, size=self._sync_rect)

        self.title_label = Label(
            text="Jarvis AI\nEnter Password to Access",
            font_name=app_font(),
            color=(0.4, 0.1, 0.8, 1),
            font_size='22sp',
            size_hint=(1, 0.5),
            halign='center'
        )
        self.title_label.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        top_card.add_widget(self.title_label)

        self.pin_display = Label(
            text="",
            font_size='30sp',
            color=(0.4, 0.1, 0.8, 1),
            size_hint=(1, 0.3)
        )
        top_card.add_widget(self.pin_display)

        self.login_btn = Button(
            text="Login",
            size_hint=(1, 0.2),
            background_color=(0.55, 0.15, 0.9, 1),
            font_size='18sp'
        )
        self.login_btn.bind(on_release=self.try_login)
        top_card.add_widget(self.login_btn)

        root.add_widget(top_card)

        # Bottom purple keypad area
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
            btn = Button(
                text=k,
                font_size='24sp',
                background_color=(0.65, 0.35, 0.95, 1),
                background_normal=''
            )
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


# ---------- Floating purple bubble (fixed touch layout) ----------
class PurpleBubble(FloatLayout):
    def __init__(self, on_tap, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (None, None)
        self.size = (80, 80)
        self.pos_hint = {'right': 0.95, 'y': 0.05}

        with self.canvas:
            Color(0.5, 0.0, 0.9, 0.85)
            self.orb = Ellipse(pos=self.pos, size=self.size)
        self.bind(pos=self._update_orb, size=self._update_orb)

        self.btn = Button(
            text="JARVIS",
            font_size='10sp',
            background_color=(0, 0, 0, 0),
            background_normal='',
            size_hint=(1, 1),
            pos=self.pos
        )
        self.btn.bind(on_release=lambda inst: on_tap())
        self.add_widget(self.btn)
        self.bind(pos=self._update_btn, size=self._update_btn)

    def _update_orb(self, instance, value):
        self.orb.pos = self.pos
        self.orb.size = self.size

    def _update_btn(self, instance, value):
        self.btn.pos = self.pos
        self.btn.size = self.size


# ---------- Main Jarvis Screen ----------
class MainScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.db = DatabaseManager()
        self.router = SmartAIRouter()
        self.silent_mode = False

        root = FloatLayout()
        with root.canvas.before:
            Color(0.05, 0.02, 0.1, 1)
            from kivy.graphics import Rectangle
            self._bg = Rectangle(pos=root.pos, size=root.size)
        root.bind(pos=self._sync_bg, size=self._sync_bg)

        self.status_label = Label(
            text="Jarvis AI Ready | Multi-Routing & Accessibility Active",
            font_name=app_font(),
            color=(0.7, 0.3, 1, 1),
            font_size='16sp',
            size_hint=(1, 0.1),
            pos_hint={'x': 0, 'top': 1}
        )
        root.add_widget(self.status_label)

        self.chat_display = Label(
            text="",
            font_name=app_font(),
            color=(1, 1, 1, 1),
            font_size='15sp',
            size_hint=(0.9, 0.5),
            pos_hint={'x': 0.05, 'y': 0.3},
            halign='left',
            valign='top'
        )
        self.chat_display.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        root.add_widget(self.chat_display)

        bubble = PurpleBubble(on_tap=self.trigger_voice_listening)
        root.add_widget(bubble)

        self._root_ref = root
        self.add_widget(root)

    def _sync_bg(self, instance, value):
        self._bg.pos = instance.pos
        self._bg.size = instance.size

    def trigger_voice_listening(self):
        self.process_command("हेलो जार्विस, सिस्टम स्टेटस चेक करो")

    def process_command(self, text):
        self.chat_display.text = "प्रोसेसिंग..."
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
        prefix = "[UI-Only Mode]\n" if self.silent_mode else "Jarvis: "
        self.chat_display.text = f"{prefix}{reply}"


class JarvisApp(App):
    def build(self):
        sm = ScreenManager()
        login = LoginScreen(APP_PASS, on_success=self.go_main, name='login')
        self.main_screen = MainScreen(name='main')
        sm.add_widget(login)
        sm.add_widget(self.main_screen)
        self.sm = sm
        return sm

    def go_main(self):
        self.sm.current = 'main'


if __name__ == "__main__":
    JarvisApp().run()
