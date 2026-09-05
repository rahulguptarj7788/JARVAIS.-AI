"""
All Android JNI calls here are dispatched onto the real Android UI
thread via @run_on_ui_thread (the official python-for-android helper),
because Kivy's own event loop runs on a separate native thread, NOT
Android's actual Java main/UI thread. Calling Java APIs directly from
Kivy's thread is exactly the class of bug that causes intermittent
crashes/silent failures on some OEM ROMs (this device is MIUI).

Since @run_on_ui_thread dispatches asynchronously and returns nothing
usable synchronously, every function here takes a `callback(ok, msg)`
instead of returning a tuple. The callback is invoked via
Clock.schedule_once, which IS documented as safe to call from any
thread -- that's what safely bridges back to Kivy's own thread so the
caller can touch Kivy widgets afterwards.
"""
from kivy import platform
from kivy.clock import Clock

if platform == "android":
    from android.runnable import run_on_ui_thread
else:
    def run_on_ui_thread(f):
        return f


def _get_activity():
    from jnius import autoclass
    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    return PythonActivity.mActivity


def _reply(callback, ok, msg):
    if callback:
        Clock.schedule_once(lambda dt: callback(ok, msg))


def go_to_home_screen(callback=None):
    if platform != "android":
        _reply(callback, False, "Desktop mode: होम स्क्रीन इंटेंट सिर्फ़ Android पर काम करता है।")
        return

    @run_on_ui_thread
    def _do():
        try:
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            activity = _get_activity()
            intent = Intent(Intent.ACTION_MAIN)
            intent.addCategory(Intent.CATEGORY_HOME)
            intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(intent)
            _reply(callback, True, "ठीक है, होम स्क्रीन पर जा रहा हूँ।")
        except Exception as e:
            _reply(callback, False, f"होम स्क्रीन खोलने में समस्या: {str(e)}")

    _do()


def toggle_torch(turn_on, callback=None):
    if platform != "android":
        _reply(callback, False, "Desktop mode: टॉर्च सिर्फ़ Android पर काम करता है।")
        return

    @run_on_ui_thread
    def _do():
        try:
            from jnius import autoclass
            Context = autoclass("android.content.Context")
            activity = _get_activity()
            camera_manager = activity.getSystemService(Context.CAMERA_SERVICE)
            camera_ids = camera_manager.getCameraIdList()
            if len(camera_ids) == 0:
                _reply(callback, False, "कैमरा/टॉर्च नहीं मिला।")
                return
            camera_manager.setTorchMode(camera_ids[0], bool(turn_on))
            _reply(callback, True, "टॉर्च ऑन कर दी।" if turn_on else "टॉर्च बंद कर दी।")
        except Exception as e:
            _reply(callback, False, f"टॉर्च त्रुटि: {str(e)}")

    _do()


def capture_and_push_screenshot(callback=None):
    # Window.screenshot() is a Kivy call, not a JNI call -- it belongs
    # on Kivy's own thread, so this one is NOT wrapped in run_on_ui_thread.
    try:
        from kivy.core.window import Window
        import tempfile, os
        path = os.path.join(tempfile.gettempdir(), "jarvis_shot.png")
        Window.screenshot(name=path)
        _reply(callback, True, "स्क्रीनशॉट ले लिया (सिर्फ़ ऐप विंडो का)।")
    except Exception as e:
        _reply(callback, False, f"स्क्रीनशॉट त्रुटि: {str(e)}")


def open_cast_intent(callback=None):
    if platform != "android":
        _reply(callback, False, "Desktop mode: कास्ट सिर्फ़ Android पर काम करता है।")
        return

    @run_on_ui_thread
    def _do():
        try:
            from jnius import autoclass
            Settings = autoclass("android.provider.Settings")
            Intent = autoclass("android.content.Intent")
            activity = _get_activity()
            activity.startActivity(Intent(Settings.ACTION_CAST_SETTINGS))
            _reply(callback, True, "कास्ट सेटिंग्स खोल रहा हूँ।")
        except Exception as e:
            _reply(callback, False, f"कास्ट खोलने में समस्या: {str(e)}")

    _do()


def play_activation_chime():
    if platform != "android":
        return

    @run_on_ui_thread
    def _do():
        try:
            from jnius import autoclass
            ToneGenerator = autoclass("android.media.ToneGenerator")
            AudioManager = autoclass("android.media.AudioManager")
            tg = ToneGenerator(AudioManager.STREAM_NOTIFICATION, 80)
            tg.startTone(ToneGenerator.TONE_PROP_BEEP, 150)
        except Exception:
            pass

    _do()


_tts_engine = {"engine": None, "ready": False}


def speak_tts(text):
    if platform != "android":
        return

    @run_on_ui_thread
    def _do():
        try:
            from jnius import autoclass, PythonJavaClass, java_method
            TextToSpeech = autoclass("android.speech.tts.TextToSpeech")
            Locale = autoclass("java.util.Locale")
            activity = _get_activity()

            if _tts_engine["engine"] is None:
                class Listener(PythonJavaClass):
                    __javainterfaces__ = ["android/speech/tts/TextToSpeech$OnInitListener"]
                    __javacontext__ = "app"

                    @java_method("(I)V")
                    def onInit(self, status):
                        if status == 0:
                            try:
                                _tts_engine["engine"].setLanguage(Locale("hi", "IN"))
                            except Exception:
                                pass
                            _tts_engine["ready"] = True

                _tts_engine["_listener"] = Listener()
                # Created here, on the real UI thread, once -- and reused
                # for every subsequent speak() call.
                _tts_engine["engine"] = TextToSpeech(activity, _tts_engine["_listener"])

            if _tts_engine["ready"]:
                _tts_engine["engine"].speak(text, TextToSpeech.QUEUE_FLUSH, None, None)
        except Exception:
            pass

    _do()


def set_wakeword_service_running(should_run, callback=None):
    if platform != "android":
        _reply(callback, False, "Desktop mode: background service सिर्फ़ Android पर चलती है।")
        return

    @run_on_ui_thread
    def _do():
        try:
            from jnius import autoclass
            SERVICE_NAME = "com.jarvis.assistant.ServiceJarviswakeword"
            service_cls = autoclass(SERVICE_NAME)
            activity = _get_activity()
            if should_run:
                service_cls.start(activity, '')
                _reply(callback, True, "24/7 wake-word service शुरू की गई (persistent notification देखें)।")
            else:
                service_cls.stop(activity)
                _reply(callback, True, "Wake-word service बंद कर दी गई।")
        except Exception as e:
            _reply(callback, False, f"Service त्रुटि: {str(e)}")

    _do()


def open_voice_assistant_settings(callback=None):
    _open_settings_action("ACTION_VOICE_INPUT_SETTINGS", False, callback)


def open_accessibility_settings(callback=None):
    _open_settings_action("ACTION_ACCESSIBILITY_SETTINGS", False, callback)


def open_app_permission_settings(callback=None):
    _open_settings_action("ACTION_APPLICATION_DETAILS_SETTINGS", True, callback)


def _open_settings_action(action, use_package_uri, callback):
    if platform != "android":
        _reply(callback, False, "Desktop mode: यह सिर्फ़ Android डिवाइस पर काम करता है।")
        return

    @run_on_ui_thread
    def _do():
        try:
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            Settings = autoclass("android.provider.Settings")
            activity = _get_activity()
            intent = Intent(getattr(Settings, action))
            if use_package_uri:
                Uri = autoclass("android.net.Uri")
                intent.setData(Uri.fromParts("package", "com.jarvis.assistant", None))
            activity.startActivity(intent)
            _reply(callback, True, "खोला जा रहा है...")
        except Exception as e:
            _reply(callback, False, f"Error: {str(e)}")

    _do()
