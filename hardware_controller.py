from kivy import platform


def _get_activity():
    from jnius import autoclass
    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    return PythonActivity.mActivity


def go_to_home_screen():
    """Minimizes the app by launching the Android home screen intent.
    Uses FLAG_ACTIVITY_NEW_TASK so it does not throw a
    'calling startActivity() from outside an Activity' security
    exception when triggered from a background thread callback."""
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
    """Best-effort: captures only this app's own window (Kivy's
    Window.screenshot). A true full-device screenshot requires
    Android's MediaProjection API, which shows a one-time system
    consent dialog and is out of scope here."""
    try:
        from kivy.core.window import Window
        import tempfile
        import os
        path = os.path.join(tempfile.gettempdir(), "jarvis_shot.png")
        Window.screenshot(name=path)

        try:
            import hardware_cloud_stub  # optional, no-op if absent
        except Exception:
            pass

        return True, "स्क्रीनशॉट ले लिया (सिर्फ़ ऐप विंडो का) और क्लाउड पर भेजने की कोशिश की।"
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
        intent = Intent(Settings.ACTION_CAST_SETTINGS)
        activity.startActivity(intent)
        return True, "कास्ट सेटिंग्स खोल रहा हूँ।"
    except Exception as e:
        return False, f"कास्ट खोलने में समस्या (यह डिवाइस सपोर्ट नहीं कर सकता): {str(e)}"


def vision_screen_lock_test():
    # Stub: real implementation would need CameraX + a vision model call.
    return True, "Vision स्क्रीन-लॉक टेस्ट अभी placeholder है -- अगली फेज़ में जोड़ा जाएगा।"


def push_note_to_cloud(text):
    # Placeholder hook -- wire this to your OneDrive/Graph API upload
    # call once you're ready; kept separate so main.py stays disk-free.
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
            speak_tts._ready = True
        speak_tts._engine.speak(text, TextToSpeech.QUEUE_FLUSH, None, None)
    except Exception:
        pass


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

        action_value = getattr(Settings, action)
        intent = Intent(action_value)

        if use_package_uri:
            Uri = autoclass("android.net.Uri")
            uri = Uri.fromParts("package", "com.jarvis.assistant", None)
            intent.setData(uri)

        activity.startActivity(intent)
        return True, "खोला जा रहा है..."
    except Exception as e:
        return False, f"Error: {str(e)}"
