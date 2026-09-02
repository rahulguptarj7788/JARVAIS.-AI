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
    return DEVANAGARI_FONT_NAME if _font_registered else "Roboto"


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
            self._top_bg = Ellipse
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


from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.scrollview import ScrollView
from kivy.graphics import RoundedRectangle, Rectangle


class GlowOrbCard(ButtonBehavior, FloatLayout):
    def __init__(self, on_tap, **kwargs):
        super().__init__(**kwargs)
        self._on_tap = on_tap
        with self.canvas.before:
            Color(0.09, 0.05, 0.14, 1)
            self._card_bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[24])
        self.bind(pos=self._sync, size=self._sync)

        with self.canvas:
            Color(0.55, 0.2, 0.95, 0.25)
            self._glow_outer = Ellipse(pos=self.pos, size=self.size)
            Color(0.55, 0.15, 0.95, 0.55)
            self._glow_mid = Ellipse(pos=self.pos, size=self.size)
            Color(0.72, 0.45, 1, 0.95)
            self._orb = Ellipse(pos=self.pos, size=self.size)
        self.bind(pos=self._sync_orb, size=self._sync_orb)

    def _sync(self, instance, value):
        self._card_bg.pos = instance.pos
        self._card_bg.size = instance.size

    def _sync_orb(self, instance, value):
        cx = self.center_x
        cy = self.center_y
        base = min(self.width, self.height) * 0.45
        for shape, scale in ((self._glow_outer, 1.0), (self._glow_mid, 0.75), (self._orb, 0.5)):
            r = base * scale
            shape.pos = (cx - r, cy - r)
            shape.size = (r * 2, r * 2)

    def on_press(self):
        if self._on_tap:
            self._on_tap()


class QuickIconButton(ButtonBehavior, BoxLayout):
    def __init__(self, label_text, on_tap, **kwargs):
        super().__init__(orientation='vertical', **kwargs)
        self._on_tap = on_tap
        with self.canvas.before:
            Color(0.22, 0.1, 0.35, 1)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[14])
        self.bind(pos=self._sync, size=self._sync)

        lbl = Label(
            text=label_text,
            font_name=app_font(),
            color=(0.85, 0.75, 1, 1),
            font_size='13sp',
            halign='center',
            valign='middle'
        )
        lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        self.add_widget(lbl)

    def _sync(self, instance, value):
        self._bg.pos = instance.pos
        self._bg.size = instance.size

    def on_press(self):
        if self._on_tap:
            self._on_tap()


class MainScreen(Screen):
    def __init__(self, on_settings, **kwargs):
        super().__init__(**kwargs)
        self.db = DatabaseManager()
        self.router = SmartAIRouter()
        self.silent_mode = False
        self.on_settings = on_settings

        root = BoxLayout(orientation='vertical')
        with root.canvas.before:
            Color(0.04, 0.02, 0.08, 1)
            self._bg = Rectangle(pos=root.pos, size=root.size)
        root.bind(pos=self._sync_bg, size=self._sync_bg)

        header = BoxLayout(orientation='horizontal', size_hint=(1, None), height=60,
                            padding=[15, 5, 15, 5])
        menu_btn = Button(text="=", font_size='22sp', size_hint=(None, 1), width=50,
                           background_color=(0, 0, 0, 0), background_normal='',
                           color=(1, 1, 1, 1))
        header.add_widget(menu_btn)

        title = Label(text="[b]JARVIS[/b] [color=#b06bffff]AI[/color]", markup=True,
                      font_size='24sp', color=(1, 1, 1, 1))
        header.add_widget(title)

        settings_btn = Button(text="*", font_size='20sp', size_hint=(None, 1), width=50,
                               background_color=(0, 0, 0, 0), background_normal='',
                               color=(1, 1, 1, 1))
        settings_btn.bind(on_release=lambda inst: self.on_settings())
        header.add_widget(settings_btn)
        root.add_widget(header)

        subtitle = Label(
            text="YOUR INTELLIGENT VOICE ASSISTANT",
            font_size='12sp',
            color=(0.6, 0.5, 0.75, 1),
            size_hint=(1, None),
            height=30
        )
        root.add_widget(subtitle)

        orb_card = GlowOrbCard(on_tap=self.trigger_voice_listening,
                                size_hint=(1, 0.32), padding=20)
        root.add_widget(orb_card)

        icons_grid = GridLayout(cols=3, rows=2, size_hint=(1, 0.22),
                                 spacing=10, padding=[15, 10, 15, 10])
        quick_actions = [
            ("नोट्स", "नोट लो"),
            ("अलार्म", "अलार्म सेट करो"),
            ("म्यूजिक", "गाना बजाओ"),
            ("टॉर्च", "टॉर्च ऑन करो"),
            ("वाई-फाई", "वाई-फाई टॉगल करो"),
            ("सेटिंग्स", "सेटिंग्स खोलो"),
        ]
        for label_text, command_text in quick_actions:
            btn = QuickIconButton(
                label_text=label_text,
                on_tap=lambda ct=command_text: self.process_command(ct)
            )
            icons_grid.add_widget(btn)
        root.add_widget(icons_grid)

        self.status_label = Label(
            text="Jarvis AI Ready | Multi-Routing & Accessibility Active",
            font_name=app_font(),
            color=(0.7, 0.3, 1, 1),
            font_size='13sp',
            size_hint=(1, None),
            height=30
        )
        root.add_widget(self.status_label)

        scroll = ScrollView(size_hint=(1, 1))
        self.chat_display = Label(
            text="",
            font_name=app_font(),
            color=(1, 1, 1, 1),
            font_size='14sp',
            size_hint=(1, None),
            halign='left',
            valign='top',
            padding=[15, 10]
        )
        self.chat_display.bind(
            width=lambda inst, val: setattr(inst, 'text_size', (val, None)),
            texture_size=lambda inst, val: setattr(inst, 'height', val[1])
        )
        scroll.add_widget(self.chat_display)
        root.add_widget(scroll)

        self.add_widget(root)

    def _sync_bg(self, instance, value):
        self._bg.pos = instance.pos
        self._bg.size = instance.size

    def trigger_voice_listening(self):
        self.process_command("हेलो जार्विस, सिस्टम स्टेटस चेक करो")

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


class SettingsScreen(Screen):
    def __init__(self, on_back, **kwargs):
        super().__init__(**kwargs)
        root = BoxLayout(orientation='vertical', padding=20, spacing=20)
        with root.canvas.before:
            Color(0.04, 0.02, 0.08, 1)
            self._bg = Rectangle(pos=root.pos, size=root.size)
        root.bind(pos=self._sync_bg, size=self._sync_bg)

        lbl = Label(
            text="Settings\n(coming in a later phase: API keys, voice, macros)",
            font_name=app_font(),
            color=(0.8, 0.7, 1, 1),
            font_size='16sp',
            halign='center'
        )
        lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        root.add_widget(lbl)

        back_btn = Button(text="Back", size_hint=(1, None), height=50,
                           background_color=(0.55, 0.15, 0.9, 1))
        back_btn.bind(on_release=lambda inst: on_back())
        root.add_widget(back_btn)

        self.add_widget(root)

    def _sync_bg(self, instance, value):
        self._bg.pos = instance.pos
        self._bg.size = instance.size


class JarvisApp(App):
    def build(self):
        sm = ScreenManager()

        login = LoginScreen(APP_PASS, on_success=self.go_main, name='login')
        self.main_screen = MainScreen(on_settings=self.go_settings_lock, name='main')
        settings_lock = LoginScreen(SETTINGS_PASS, on_success=self.go_settings, name='settings_lock')
        settings_screen = SettingsScreen(on_back=self.go_main, name='settings')

        sm.add_widget(login)
        sm.add_widget(self.main_screen)
        sm.add_widget(settings_lock)
        sm.add_widget(settings_screen)
        self.sm = sm
        return sm

    def go_main(self):
        self.sm.current = 'main'

    def go_settings_lock(self):
        self.sm.current = 'settings_lock'

    def go_settings(self):
        self.sm.current = 'settings'


if __name__ == "__main__":
    JarvisApp().run()
