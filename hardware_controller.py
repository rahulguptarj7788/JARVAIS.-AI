from kivy import platform


def _get_activity():
    from jnius import autoclass
    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    return PythonActivity.mActivity


def go_to_home_screen():
    if platform != "android":
        return False, "Desktop mode: होम स्क्रीन इंटेंट सिर्फ़ Android पर काम करता है।"
    try:
        from jnius import autoclass
        Intent = autoclass("android.content.Intent")
        activity = _get_activity()
        intent = Intent(Intent.ACTION_MAIN)
        intent.addCategory(Intent.CATEGORY_HOME)
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        activity.startActivity(intent)
        return True, "ठीक है, होम स्क्रीन पर जा रहा हूँ।"
    except Exception as e:
        return False, f"होम स्क्रीन खोलने में समस्या: {str(e)}"


def toggle_torch(turn_on):
    if platform != "android":
        return False, "Desktop mode: टॉर्च सिर्फ़ Android पर काम करता है।"
    try:
        from jnius import autoclass
        Context = autoclass("android.content.Context")
        activity = _get_activity()
        camera_manager = activity.getSystemService(Context.CAMERA_SERVICE)
        camera_ids = camera_manager.getCameraIdList()
        if len(camera_ids) == 0:
            return False, "कैमरा/टॉर्च नहीं मिला।"
        camera_manager.setTorchMode(camera_ids[0], bool(turn_on))
        return True, "टॉर्च ऑन कर दी।" if turn_on else "टॉर्च बंद कर दी।"
    except Exception as e:
        return False, f"टॉर्च त्रुटि: {str(e)}"


def capture_and_push_screenshot():
    try:
        from kivy.core.window import Window
        import tempfile, os
        path = os.path.join(tempfile.gettempdir(), "jarvis_shot.png")
        Window.screenshot(name=path)
        return True, "स्क्रीनशॉट ले लिया (सिर्फ़ ऐप विंडो का)।"
    except Exception as e:
        return False, f"स्क्रीनशॉट त्रुटि: {str(e)}"


def open_cast_intent():
    if platform != "android":
        return False, "Desktop mode: कास्ट सिर्फ़ Android पर काम करता है।"
    try:
        from jnius import autoclass
        Settings = autoclass("android.provider.Settings")
        Intent = autoclass("android.content.Intent")
        activity = _get_activity()
        activity.startActivity(Intent(Settings.ACTION_CAST_SETTINGS))
        return True, "कास्ट सेटिंग्स खोल रहा हूँ।"
    except Exception as e:
        return False, f"कास्ट खोलने में समस्या: {str(e)}"


def play_activation_chime():
    if platform != "android":
        return
    try:
        from jnius import autoclass
        ToneGenerator = autoclass("android.media.ToneGenerator")
        AudioManager = autoclass("android.media.AudioManager")
        tg = ToneGenerator(AudioManager.STREAM_NOTIFICATION, 80)
        tg.startTone(ToneGenerator.TONE_PROP_BEEP, 150)
    except Exception:
        pass


def speak_tts(text):
    if platform != "android":
        return
    try:
        from jnius import autoclass
        TextToSpeech = autoclass("android.speech.tts.TextToSpeech")
        activity = _get_activity()
        if not hasattr(speak_tts, "_engine"):
            speak_tts._engine = TextToSpeech(activity, None)
        speak_tts._engine.speak(text, TextToSpeech.QUEUE_FLUSH, None, None)
    except Exception:
        pass


def set_wakeword_service_running(should_run):
    if platform != "android":
        return False, "Desktop mode: background service सिर्फ़ Android पर चलती है।"
    try:
        from jnius import autoclass
        SERVICE_NAME = "com.jarvis.assistant.ServiceJarviswakeword"
        if should_run:
            service = autoclass(SERVICE_NAME)
            service.start(_get_activity(), '')
            return True, "24/7 wake-word service शुरू की गई (persistent notification देखें)।"
        else:
            service = autoclass(SERVICE_NAME)
            service.stop(_get_activity())
            return True, "Wake-word service बंद कर दी गई।"
    except Exception as e:
        return False, f"Service त्रुटि: {str(e)}"


def open_voice_assistant_settings():
    return _open_settings_action("ACTION_VOICE_INPUT_SETTINGS", False)


def open_accessibility_settings():
    return _open_settings_action("ACTION_ACCESSIBILITY_SETTINGS", False)


def open_app_permission_settings():
    return _open_settings_action("ACTION_APPLICATION_DETAILS_SETTINGS", True)


def _open_settings_action(action, use_package_uri):
    if platform != "android":
        return False, "Desktop mode: यह सिर्फ़ Android डिवाइस पर काम करता है।"
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
        return True, "खोला जा रहा है..."
    except Exception as e:
        return False, f"Error: {str(e)}"
