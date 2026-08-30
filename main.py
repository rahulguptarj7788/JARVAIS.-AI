import os
import sys
import re
import ast
import json
import time
import sqlite3
import threading
import requests
from kivy.app import App
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.clock import Clock

# API Keys loaded directly from GitHub Secrets / Environment
GROQ_KEYS = [
    os.environ.get("GROQ_API_KEY_1", ""),
    os.environ.get("GROQ_API_KEY_2", "")
]
GEMINI_KEYS = [
    os.environ.get("GEMINI_API_KEY_1", ""),
    os.environ.get("GEMINI_API_KEY_2", "")
]
OPENROUTER_KEYS = [
    os.environ.get("OPENROUTER_API_KEY_1", ""),
    os.environ.get("OPENROUTER_API_KEY_2", "")
]
CEREBRAS_KEYS = [
    os.environ.get("CEREBRAS_API_KEY_1", ""),
    os.environ.get("CEREBRAS_API_KEY_2", "")
]

ONEDRIVE_CLIENT_ID = os.environ.get("ONEDRIVE_CLIENT_ID", "")
ONEDRIVE_CLIENT_SECRET = os.environ.get("ONEDRIVE_CLIENT_SECRET", "")
ONEDRIVE_REFRESH_TOKEN = os.environ.get("ONEDRIVE_REFRESH_TOKEN", "")

# ----------------------------------------------------
# 1. SQLite Memory Engine (Local Storage)
# ----------------------------------------------------
class LocalMemory:
    def __init__(self, db_name="jarvis_memory.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        self.conn.commit()

    def set_data(self, key, value):
        self.cursor.execute("INSERT OR REPLACE INTO memory (key, value) VALUES (?, ?)", (key, value))
        self.conn.commit()

    def get_data(self, key):
        self.cursor.execute("SELECT value FROM memory WHERE key = ?", (key,))
        row = self.cursor.fetchone()
        return row[0] if row else None

db = LocalMemory()

# ----------------------------------------------------
# 2. Offline Calculator Engine (0% API Cost)
# ----------------------------------------------------
def calculate_expression(expr):
    try:
        clean_expr = re.sub(r'[^0-9\+\-\*\/\.\(\)\%]', '', expr)
        if '%' in clean_expr:
            clean_expr = clean_expr.replace('%', '/100')
        node = ast.parse(clean_expr, mode='eval')
        compiled = compile(node, '<string>', 'eval')
        result = eval(compiled, {"__builtins__": None}, {})
        return f"उत्तर: {result}"
    except Exception:
        return None

# ----------------------------------------------------
# 3. Hardware System Actions (Android Native Bridge)
# ----------------------------------------------------
def control_hardware(command):
    cmd = command.lower()
    try:
        from jnius import autoclass
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        Context = autoclass('android.content.Context')
        Intent = autoclass('android.content.Intent')
        Uri = autoclass('android.net.Uri')
        current_activity = PythonActivity.mActivity

        if "volume up" in cmd or "आवाज बढ़ाओ" in cmd:
            audio_manager = current_activity.getSystemService(Context.AUDIO_SERVICE)
            audio_manager.adjustStreamVolume(3, 1, 1)
            return "आवाज़ बढ़ा दी गई है।"
        
        elif "volume down" in cmd or "आवाज कम करो" in cmd:
            audio_manager = current_activity.getSystemService(Context.AUDIO_SERVICE)
            audio_manager.adjustStreamVolume(3, -1, 1)
            return "आवाज़ कम कर दी गई है।"

        elif "silent mode" in cmd or "साइलेंट मोड" in cmd:
            audio_manager = current_activity.getSystemService(Context.AUDIO_SERVICE)
            audio_manager.setRingerMode(0)
            return "फोन साइलेंट मोड पर सेट हो गया है।"

        elif "google" in cmd and "search" in cmd:
            query = cmd.replace("google search", "").strip()
            intent = Intent(Intent.ACTION_VIEW, Uri.parse(f"https://www.google.com/search?q={query}"))
            current_activity.startActivity(intent)
            return f"गूगल पर {query} सर्च कर रहा हूँ।"

    except Exception as e:
        pass

    return None

# ----------------------------------------------------
# 4. Multi-API Failover & Dynamic Router
# ----------------------------------------------------
def query_ai_models(prompt):
    # Try Groq API Keys first
    for key in GROQ_KEYS:
        if key:
            try:
                res = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}]},
                    timeout=5
                )
                if res.status_code == 200:
                    return res.json()['choices'][0]['message']['content']
            except Exception:
                continue

    # Failover to Gemini API Keys
    for key in GEMINI_KEYS:
        if key:
            try:
                res = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}",
                    headers={"Content-Type": "application/json"},
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    timeout=5
                )
                if res.status_code == 200:
                    return res.json()['candidates'][0]['content']['parts'][0]['text']
            except Exception:
                continue

    return "माफ़ कीजिए, सभी AI API सर्वर इस समय व्यस्त हैं।"

# ----------------------------------------------------
# 5. Core Intent Processing Engine
# ----------------------------------------------------
def process_user_input(text):
    hw_res = control_hardware(text)
    if hw_res:
        return hw_res

    if any(op in text for op in ['+', '-', '*', '/', 'गुणा', 'भाग', 'प्लस', 'माइनस', '%']):
        math_res = calculate_expression(text)
        if math_res:
            return math_res

    return query_ai_models(text)

# ----------------------------------------------------
# 6. Kivy Purple Floating Overlay UI
# ----------------------------------------------------
class FloatingOverlay(FloatLayout):
    def __init__(self, **kwargs):
        super(FloatingOverlay, self).__init__(**kwargs)
        
        self.bubble_btn = Button(
            text="JARVIS",
            size_hint=(None, None),
            size=(140, 140),
            pos_hint={'center_x': 0.5, 'center_y': 0.15},
            background_normal='',
            background_color=(0.5, 0.0, 0.9, 1.0)
        )
        self.bubble_btn.bind(on_press=self.on_trigger_listening)
        self.add_widget(self.bubble_btn)

        self.status_label = Label(
            text="Jarvis Active",
            pos_hint={'center_x': 0.5, 'center_y': 0.25},
            color=(0.8, 0.5, 1.0, 1)
        )
        self.add_widget(self.status_label)

    def on_trigger_listening(self, instance):
        self.status_label.text = "Processing..."
        threading.Thread(target=self.run_assistant_workflow).start()

    def run_assistant_workflow(self):
        sample_query = "150 * 12 %"
        response = process_user_input(sample_query)
        Clock.schedule_once(lambda dt: self.update_ui_response(response))

    def update_ui_response(self, text):
        self.status_label.text = text

class JarvisApp(App):
    def build(self):
        return FloatingOverlay()

if __name__ == "__main__":
    JarvisApp().run()

