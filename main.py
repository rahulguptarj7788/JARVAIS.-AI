import os
import sys
import sqlite3
import json
import requests
import threading
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.clock import Clock
from kivy.graphics import Color, Ellipse

APP_PASS = "01062013"
SETTINGS_PASS = "18112023"

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
        self.gemini_keys = [os.environ.get("GEMINI_API_KEY_1"), os.environ.get("GEMINI_API_KEY_2")]
        self.openrouter_keys = [os.environ.get("OPENROUTER_API_KEY_1"), os.environ.get("OPENROUTER_API_KEY_2")]
        self.cerebras_keys = [os.environ.get("CEREBRAS_API_KEY_1"), os.environ.get("CEREBRAS_API_KEY_2")]
        self.active_index = 0

    def query_groq(self, prompt):
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

class PurpleBubbleOverlay(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (None, None)
        self.size = (80, 80)
        self.pos_hint = {'right': 0.95, 'y': 0.05}
        
        with self.canvas:
            Color(0.5, 0.0, 0.9, 0.8)
            self.orb = Ellipse(pos=self.pos, size=self.size)

        self.btn = Button(
            text="JARVIS",
            background_color=(0,0,0,0),
            size_hint=(1, 1),
            pos_hint={'x': 0, 'y': 0}
        )
        self.btn.bind(on_release=self.on_tap)
        self.add_widget(self.btn)

    def on_tap(self, instance):
        app = App.get_running_app()
        app.trigger_voice_listening()

class JarvisUI(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', **kwargs)
        self.db = DatabaseManager()
        self.router = SmartAIRouter()
        self.authenticated = False
        self.silent_mode = False

        self.status_label = Label(
            text="[ Jarvis AI Protection System ]\nकृपया ऐप पासवर्ड दर्ज करें:",
            size_hint=(1, 0.2),
            color=(0.7, 0.3, 1, 1)
        )
        self.add_widget(self.status_label)

        self.pass_input = TextInput(
            password=True,
            multiline=False,
            size_hint=(1, 0.1)
        )
        self.add_widget(self.pass_input)

        self.submit_btn = Button(
            text="Unlock App",
            size_hint=(1, 0.1),
            background_color=(0.5, 0.1, 0.9, 1)
        )
        self.submit_btn.bind(on_release=self.check_password)
        self.add_widget(self.submit_btn)

        self.chat_display = Label(
            text="",
            size_hint=(1, 0.5),
            color=(1, 1, 1, 1)
        )

    def check_password(self, instance):
        if self.pass_input.text == APP_PASS:
            self.authenticated = True
            self.remove_widget(self.pass_input)
            self.remove_widget(self.submit_btn)
            self.status_label.text = "Jarvis AI Ready | Multi-Routing & Accessibility Active"
            self.add_widget(self.chat_display)
            self.add_widget(PurpleBubbleOverlay())
        else:
            self.status_label.text = "गलत पासवर्ड! पुन: प्रयास करें:"
            self.pass_input.text = ""

    def update_ui_reply(self, reply):
        if self.silent_mode:
            self.chat_display.text = f"[UI-Only Mode]\n{reply}"
        else:
            self.chat_display.text = f"Jarvis: {reply}"

    def async_process_command(self, text):
        cmd = text.lower()
        if "म्यूट" in cmd or "silent mode" in cmd:
            self.silent_mode = True
            Clock.schedule_once(lambda dt: self.update_ui_reply("न्यूरल वॉयस म्यूट कर दी गई है।"))
            return

        reply = self.router.ask(text)
        self.db.add_note(f"User: {text} | AI: {reply}")
        Clock.schedule_once(lambda dt: self.update_ui_reply(reply))

    def process_command(self, text):
        if not self.authenticated:
            return
        self.chat_display.text = "प्रोसेसिंग..."
        threading.Thread(target=self.async_process_command, args=(text,), daemon=True).start()

class JarvisApp(App):
    def build(self):
        self.root_ui = JarvisUI()
        return self.root_ui

    def trigger_voice_listening(self):
        if self.root_ui.authenticated:
            self.root_ui.process_command("हेलो जार्विस, सिस्टम स्टेटस चेक करो")

if __name__ == "__main__":
    JarvisApp().run()

