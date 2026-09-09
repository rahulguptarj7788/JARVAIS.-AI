"""
Background foreground-service entry point. Event-driven: SpeechRecognizer
callbacks fire on this process's Looper thread; the next listen cycle is
only scheduled from inside onResults/onError via Handler.postDelayed --
never via a blocking time.sleep(), which would freeze the Looper and
silently stop all recognition callbacks (this was audited and fixed
in the previous pass, kept as-is here per the no-regression directive).

This is an in-app/background-service wake-word listener, NOT a full
Android VoiceInteractionService replacement of "Hey Google" -- see
architecture notes: a true OS-level default-assistant swap needs a
custom manifest + service metadata that this build pipeline can't
safely support yet.
"""
try:
    from jnius import autoclass, PythonJavaClass, java_method

    PythonService = autoclass('org.kivy.android.PythonService')
    Context = autoclass('android.content.Context')
    NotificationBuilder = autoclass('android.app.Notification$Builder')
    NotificationManager = autoclass('android.app.NotificationManager')
    NotificationChannel = autoclass('android.app.NotificationChannel')
    Build_VERSION = autoclass('android.os.Build$VERSION')
    SpeechRecognizer = autoclass('android.speech.SpeechRecognizer')
    RecognizerIntent = autoclass('android.speech.RecognizerIntent')
    Intent = autoclass('android.content.Intent')
    Handler = autoclass('android.os.Handler')
    Looper = autoclass('android.os.Looper')

    service = PythonService.mService
    _JNI_OK = True
except Exception:
    _JNI_OK = False
    service = None

CHANNEL_ID = "jarvis_wakeword_channel"
RESTART_DELAY_MS = 800
BUSY_RETRY_DELAY_MS = 2000
ERROR_RECOGNIZER_BUSY = 8

_handler = None
_recognizer = None
_recognizer_intent = None

WAKE_PHRASES = ["jarvis", "hey jarvis", "जार्विस"]


def _ensure_notification():
    try:
        nm = service.getSystemService(Context.NOTIFICATION_SERVICE)
        if Build_VERSION.SDK_INT >= 26:
            channel = NotificationChannel(CHANNEL_ID, "Jarvis Wake-Word", NotificationManager.IMPORTANCE_LOW)
            nm.createNotificationChannel(channel)
            builder = NotificationBuilder(service, CHANNEL_ID)
        else:
            builder = NotificationBuilder(service)
        builder.setContentTitle("Jarvis AI")
        builder.setContentText("वेक-वर्ड सुन रहा हूँ...")
        builder.setOngoing(True)
        service.startForeground(1, builder.build())
    except Exception:
        pass


def _push_wake_event(text):
    try:
        from db import ChatDatabase
        db = ChatDatabase()
        db.push_wake_event(text)
    except Exception:
        pass


def _start_listening():
    try:
        _recognizer.startListening(_recognizer_intent)
    except Exception:
        _schedule_restart(RESTART_DELAY_MS)


def _schedule_restart(delay_ms):
    try:
        _handler.postDelayed(_start_listening, delay_ms)
    except Exception:
        pass


if _JNI_OK:
    class RecognitionListener(PythonJavaClass):
        __javainterfaces__ = ["android/speech/RecognitionListener"]
        __javacontext__ = "app"

        @java_method("(Landroid/os/Bundle;)V")
        def onResults(self, results):
            try:
                matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                if matches and matches.size() > 0:
                    text = matches.get(0)
                    if text and any(p in text.lower() for p in WAKE_PHRASES):
                        _push_wake_event(text)
            except Exception:
                pass
            _schedule_restart(RESTART_DELAY_MS)

        @java_method("(I)V")
        def onError(self, error):
            delay = BUSY_RETRY_DELAY_MS if error == ERROR_RECOGNIZER_BUSY else RESTART_DELAY_MS
            _schedule_restart(delay)

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


def main():
    global _recognizer, _recognizer_intent, _handler
    if not _JNI_OK:
        return
    try:
        _handler = Handler(Looper.getMainLooper())
        _ensure_notification()

        listener = RecognitionListener()
        _recognizer = SpeechRecognizer.createSpeechRecognizer(service)
        _recognizer.setRecognitionListener(listener)

        _recognizer_intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
        _recognizer_intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        _recognizer_intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "hi-IN")

        _start_listening()
    except Exception:
        pass


main()
