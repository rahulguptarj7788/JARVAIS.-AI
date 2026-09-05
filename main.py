import threading
from datetime import datetime
from kivy import platform
from kivy.app import App
from kivy.lang import Builder
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
import traceback
import os

from router import SmartAIRouter, strip_think_tags
import hardware_controller as hw

Window.softinput_mode = 'below_target'
Builder.load_file('ui_layout.kv')

APP_PASS = "01062013"
SETTINGS_PASS = "18112023"

BG_DARK = (0.051, 0.027, 0.106, 1)
BG_PANEL = (0.071, 0.035, 0.141, 1)
ACCENT_PURPLE = (0.42, 0.15, 0.85, 1)

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


def hindi_font():
    """Use for any widget that will render Hindi/Devanagari text.
    Roboto (set globally via ui_layout.kv) does not have Devanagari
    glyphs, so those specific widgets must override it explicitly."""
    return DEVANAGARI_FONT_NAME if _font_registered else "Roboto"


# ---------------- Volatile RAM-only session store (no disk writes) ----------------
class SessionMemory:
    """Zero-disk-storage: everything lives only in this process's RAM and
    is lost when the app is killed. Notes are pushed straight to OneDrive
    instead of being written to a local file/DB."""
    def __init__(self):
        self.notes = []          # list of {"text":..., "time":...}
        self.chat_history = []   # list of {"role":..., "content":...}

    def add_note(self, content):
        self.notes.append({"text": content, "time": datetime.now().isoformat()})

    def add_turn(self, role, content):
        self.chat_history.append({"role": role, "content": content})


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

        self.title_label = Label(text="Jarvis AI\nEnter Password to Access", font_name=hindi_font(),
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


# ---------------- 48dp min touch-target icon button (Settings gear) ----------------
class TouchTargetIconButton(ButtonBehavior, AnchorLayout):
    """Outer clickable area is forced to >= 48dp x 48dp (Android's
    minimum recommended touch target), even though the visible icon
    inside can stay small."""
    def __init__(self, icon_text, on_tap, icon_color=(1, 1, 1, 1), **kwargs):
        kwargs.setdefault('size_hint', (None, None))
        kwargs.setdefault('size', (dp(48), dp(48)))
        super().__init__(**kwargs)
        self._on_tap = on_tap
        self.icon_lbl = Label(text=icon_text, font_size='20sp', color=icon_color)
        self.add_widget(self.icon_lbl)

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

        lbl = Label(text=label_text, font_name=hindi_font(), color=(0.9, 0.82, 1, 1),
                    font_size='13sp', halign='center', valign='middle')
        lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        self.add_widget(lbl)

    def _sync(self, instance, value):
        self._bg.pos = instance.pos
        self._bg.size = instance.size

    def on_press(self):
        if self._on_tap:
            self._on_tap()


HOME_COMMAND_PHRASES = [
    "go to home screen", "minimize apps", "apps close karo",
    "होम स्क्रीन", "मिनिमाइज़",
]


# ---------------- Main Screen ----------------
class MainScreen(Screen):
    DRAWER_WIDTH = dp(260)

    def __init__(self, on_settings, **kwargs):
        super().__init__(**kwargs)
        self.memory = SessionMemory()
        self.router = SmartAIRouter()
        self.on_settings = on_settings
        self.drawer_open = False
        self.wake_word_active = False
        self.tts_muted = False

        outer = FloatLayout()

        content = BoxLayout(orientation='vertical', size_hint=(1, 1))
        with content.canvas.before:
            Color(*BG_DARK)
            self._bg = Rectangle(pos=content.pos, size=content.size)
        content.bind(pos=self._sync_bg, size=self._sync_bg)

        header = BoxLayout(orientation='horizontal', size_hint=(1, None), height=60, padding=[15, 5, 15, 5])
        menu_btn = TouchTargetIconButton(icon_text="=", on_tap=self.toggle_drawer)
        header.add_widget(menu_btn)

        title = Label(text="[b]JARVIS[/b] [color=#b06bffff]AI[/color]", markup=True,
                      font_size='24sp', color=(1, 1, 1, 1))
        header.add_widget(title)

        settings_btn = TouchTargetIconButton(icon_text="\u2699", on_tap=self.on_settings,
                                              icon_color=ACCENT_PURPLE)
        header.add_widget(settings_btn)
        content.add_widget(header)

        content.add_widget(Widget(size_hint=(1, None), height=dp(10)))

        subtitle = Label(text="YOUR INTELLIGENT VOICE ASSISTANT", font_size='12sp',
                          color=(0.6, 0.5, 0.75, 1), size_hint=(1, None), height=30)
        content.add_widget(subtitle)

        content.add_widget(Widget(size_hint=(1, None), height=dp(20)))

        orb_wrap = AnchorLayout(size_hint=(1, 0.42))
        orb_btn = OrbButton(on_tap=self.trigger_voice_listening, size_hint=(0.94, 1))
        orb_wrap.add_widget(orb_btn)
        content.add_widget(orb_wrap)

        icons_grid = GridLayout(cols=5, rows=1, size_hint=(1, 0.12), spacing=8, padding=[10, 8, 10, 8])
        quick_actions = [
            ("नोट्स", "नोट लो"),
            ("टॉर्च", "टॉर्च ऑन करो"),
            ("स्क्रीनशॉट", "स्क्रीनशॉट लो"),
            ("टीवी", "टीवी कास्ट करो"),
            ("होम", "go to home screen"),
        ]
        for label_text, command_text in quick_actions:
            btn = QuickIconButton(label_text=label_text, on_tap=lambda ct=command_text: self.process_command(ct))
            icons_grid.add_widget(btn)
        content.add_widget(icons_grid)

        self.chat_scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        self.chat_display = Label(text="", markup=True, font_name=hindi_font(), color=(1, 1, 1, 1), font_size='14sp',
                                   size_hint=(1, None), halign='left', valign='top', padding=[15, 10])
        self.chat_display.bind(
            width=lambda inst, val: setattr(inst, 'text_size', (val, None)),
            texture_size=self._on_chat_texture_size
        )
        self.chat_scroll.add_widget(self.chat_display)
        content.add_widget(self.chat_scroll)

        input_bar = BoxLayout(orientation='horizontal', size_hint=(1, None), height=dp(54),
                               padding=[16, 4, 6, 4], spacing=8)
        with input_bar.canvas.before:
            Color(*BG_PANEL)
            self._input_bar_bg = RoundedRectangle(pos=input_bar.pos, size=input_bar.size, radius=[dp(27)])
        input_bar.bind(pos=self._sync_input_bar, size=self._sync_input_bar)

        self.chat_input = TextInput(
            hint_text="टाइप करें...",
            multiline=False,
            size_hint=(1, 1),
            background_color=(0, 0, 0, 0),
            foreground_color=(1, 1, 1, 1),
            hint_text_color=(0.6, 0.5, 0.7, 1),
            cursor_color=ACCENT_PURPLE,
            padding=[12, 14, 12, 12],
            font_name=hindi_font(),
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
        drawer_header.add_widget(Label(text="[b]Menu[/b]", markup=True, font_size='18sp', color=(1, 1, 1, 1)))
        close_btn = TouchTargetIconButton(icon_text="X", on_tap=self.toggle_drawer)
        drawer_header.add_widget(close_btn)
        self.drawer.add_widget(drawer_header)

        self.drawer.add_widget(Label(text="Model", font_size='13sp', color=(0.7, 0.6, 0.85, 1),
                                      size_hint=(1, None), height=22, halign='left'))
        model_col = BoxLayout(orientation='vertical', size_hint=(1, None), height=220, spacing=6)
        for mode_name in ["auto", "gemini", "groq", "openrouter"]:
            tb = ToggleButton(text=mode_name.capitalize(), group='model_mode',
                               state='down' if mode_name == 'auto' else 'normal',
                               background_color=ACCENT_PURPLE, size_hint=(1, None), height=38)
            tb.bind(on_release=lambda inst, m=mode_name: self.router.set_mode(m))
            model_col.add_widget(tb)
        self.drawer.add_widget(model_col)

        self.drawer.add_widget(Widget(size_hint=(1, 1)))
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

    def trigger_voice_listening(self):
        self.process_command("हेलो जार्विस, सिस्टम स्टेटस चेक करो")

    def on_send(self, *args):
        text = self.chat_input.text.strip()
        if not text:
            return
        self.chat_input.text = ''
        self.process_command(text)

    def _append_system_msg(self, msg):
        self.chat_display.text += f"\n[color=#b06bffff]System:[/color] {msg}\n"

    def _speak(self, text):
        if not self.tts_muted:
            hw.speak_tts(text)

    def process_command(self, text):
        self.chat_display.text += f"\n[color=#4fd1ff]You:[/color] {text}\n"
        self.memory.add_turn("user", text)

        lower = text.lower()

        # Home-screen minimize command (handled locally, no AI call)
        if any(phrase in lower for phrase in HOME_COMMAND_PHRASES):
            ok, msg = hw.go_to_home_screen()
            self.chat_display.text += f"[color=#b06bffff]Jarvis:[/color] {msg}\n"
            self._speak(msg)
            return

        # Torch
        if "टॉर्च" in lower or "torch" in lower or "flashlight" in lower:
            state_on = "बंद" not in lower and "off" not in lower
            ok, msg = hw.toggle_torch(state_on)
            self.chat_display.text += f"[color=#b06bffff]Jarvis:[/color] {msg}\n"
            self._speak(msg)
            return

        # Screenshot (best-effort: captures this app's own window only --
        # true full-screen capture needs Android's MediaProjection consent
        # dialog, which is out of scope here)
        if "स्क्रीनशॉट" in lower or "screenshot" in lower:
            ok, msg = hw.capture_and_push_screenshot()
            self.chat_display.text += f"[color=#b06bffff]Jarvis:[/color] {msg}\n"
            self._speak(msg)
            return

        # TV cast (stub -- opens Android's built-in Cast/output switcher)
        if "टीवी" in lower or "cast" in lower:
            ok, msg = hw.open_cast_intent()
            self.chat_display.text += f"[color=#b06bffff]Jarvis:[/color] {msg}\n"
            self._speak(msg)
            return

        # Vision API screen-lock test (stub)
        if "screen lock test" in lower or "स्क्रीन लॉक टेस्ट" in lower:
            ok, msg = hw.vision_screen_lock_test()
            self.chat_display.text += f"[color=#b06bffff]Jarvis:[/color] {msg}\n"
            self._speak(msg)
            return

        if lower.startswith('set api '):
            self.handle_set_api(text)
            return

        if "नोट लो" in lower or "note" in lower:
            self.memory.add_note(text)
            hw.push_note_to_cloud(text)
            self.chat_display.text += "[color=#b06bffff]Jarvis:[/color] नोट क्लाउड पर भेज दिया गया।\n"
            self._speak("नोट क्लाउड पर भेज दिया गया।")
            return

        self.chat_display.text += "प्रोसेसिंग..."
        threading.Thread(target=self._async_process, args=(text,), daemon=True).start()

    def handle_set_api(self, text):
        parts = text.split(maxsplit=3)
        if len(parts) < 4:
            self._append_system_msg("प्रारूप: set api <provider> <key>")
            return
        provider = parts[2].lower()
        key = parts[3]
        ok = self.router.set_manual_key(provider, key)
        if ok:
            self._append_system_msg(f"{provider} API key इस सेशन के लिए सेट हो गई (RAM only, restart पर मिट जाएगी)।")
        else:
            self._append_system_msg(f"अज्ञात provider: {provider}")

    def _async_process(self, text):
        reply, fail_count = self.router.ask(text)
        self.memory.add_turn("assistant", reply)
        Clock.schedule_once(lambda dt: self._update_reply(reply, fail_count))

    def _update_reply(self, reply, fail_count):
        if self.chat_display.text.endswith("प्रोसेसिंग..."):
            self.chat_display.text = self.chat_display.text[:-len("प्रोसेसिंग...")]

        if reply is None:
            msg = "सभी API Keys विफल रही।"
            self.chat_display.text += f"\n[color=#ff5c5c]Jarvis:[/color] {msg}\n"
            self._speak(msg)
            return

        self.chat_display.text += f"\n[color=#b06bffff]Jarvis:[/color] {reply}\n"
        self._speak(reply)

        if fail_count > 0:
            # Silent footer log -- shown in UI, never spoken
            self.chat_display.text += f"[color=#888888][size=11]{{Logs: {fail_count}/6 Keys Failed}}[/size][/color]\n"

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

        title_lbl = Label(text="Settings", font_name=hindi_font(), color=(0.8, 0.7, 1, 1),
                           font_size='20sp', size_hint=(1, None), height=40)
        root.add_widget(title_lbl)

        self.status_lbl = Label(text="", font_size='13sp', color=(0.7, 0.9, 0.7, 1),
                                 size_hint=(1, None), height=40, halign='center')
        self.status_lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        root.add_widget(self.status_lbl)

        wake_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=48)
        wake_row.add_widget(Label(text="Wake Word Detection (Jarvis)", font_name=hindi_font(),
                                   color=(0.85, 0.8, 0.95, 1), font_size='14sp'))
        wake_switch = Switch(active=False)
        wake_switch.bind(active=lambda inst, val: setattr(self.main_screen_ref, 'wake_word_active', val))
        wake_row.add_widget(wake_switch)
        root.add_widget(wake_row)

        tts_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=48)
        tts_row.add_widget(Label(text="Mute / Unmute Voice Output", font_name=hindi_font(),
                                  color=(0.85, 0.8, 0.95, 1), font_size='14sp'))
        tts_switch = Switch(active=False)
        tts_switch.bind(active=lambda inst, val: setattr(self.main_screen_ref, 'tts_muted', val))
        tts_row.add_widget(tts_switch)
        root.add_widget(tts_row)

        voice_btn = Button(text="Set Default Voice Assistant", size_hint=(1, None), height=55,
                            background_color=ACCENT_PURPLE)
        voice_btn.bind(on_release=lambda inst: self._run_intent(hw.open_voice_assistant_settings))
        root.add_widget(voice_btn)

        accessibility_btn = Button(text="Enable Accessibility Service", size_hint=(1, None), height=55,
                                    background_color=ACCENT_PURPLE)
        accessibility_btn.bind(on_release=lambda inst: self._run_intent(hw.open_accessibility_settings))
        root.add_widget(accessibility_btn)

        perms_btn = Button(text="App Permissions", size_hint=(1, None), height=55,
                            background_color=ACCENT_PURPLE)
        perms_btn.bind(on_release=lambda inst: self._run_intent(hw.open_app_permission_settings))
        root.add_widget(perms_btn)

        root.add_widget(Widget(size_hint=(1, 1)))

        back_btn = Button(text="Back", size_hint=(1, None), height=50, background_color=BG_PANEL)
        back_btn.bind(on_release=lambda inst: on_back())
        root.add_widget(back_btn)
        self.add_widget(root)

    def _run_intent(self, fn):
        ok, msg = fn()
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
