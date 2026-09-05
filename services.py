"""
Background foreground-service entry point (separate process from the
main app, started via android.services in buildozer.spec).

Event-driven loop: SpeechRecognizer's callbacks (onResults/onError) are
delivered on this process's main Looper thread. The old version called
time.sleep(4) right after startListening(), which BLOCKED that same
Looper thread -- meaning recognition callbacks could not be delivered
while asleep. Fixed by only restarting listening from inside the
callbacks themselves (event-driven), never via a blocking sleep loop.
"""
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
CHANNEL_ID = "jarvis_wakeword_channel"

RESTART_DELAY_MS = 800          # normal restart after a finished session
BUSY_RETRY_DELAY_MS = 2000      # longer backoff specifically for ERROR_RECOGNIZER_BUSY
ERROR_RECOGNIZER_BUSY = 8       # SpeechRecognizer.ERROR_RECOGNIZER_BUSY constant value

_handler = Handler(Looper.getMainLooper())
_recognizer = None
_recognizer_intent = None


def _ensure_notification():
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
    notification = builder.build()
    try:
        service.startForeground(1, notification)
    except Exception:
        pass


def _push_wake_event(text):
    from db import ChatDatabase
    db = ChatDatabase()
    db.push_wake_event(text)


def _start_listening():
    try:
        _recognizer.startListening(_recognizer_intent)
    except Exception:
        _schedule_restart(RESTART_DELAY_MS)


def _schedule_restart(delay_ms):
    _handler.postDelayed(_start_listening, delay_ms)


class RecognitionListener(PythonJavaClass):
    __javainterfaces__ = ["android/speech/RecognitionListener"]
    __javacontext__ = "app"

    @java_method("(Landroid/os/Bundle;)V")
    def onResults(self, results):
        try:
            matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
            if matches and matches.size() > 0:
                text = matches.get(0)
                if text and ("jarvis" in text.lower() or "जार्विस" in text):
                    _push_wake_event(text)
        except Exception:
            pass
        _schedule_restart(RESTART_DELAY_MS)

    @java_method("(I)V")
    def onError(self, error):
        # ERROR_RECOGNIZER_BUSY needs a longer backoff or we just hammer
        # the recognizer with restarts and it stays busy indefinitely.
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
    global _recognizer, _recognizer_intent
    _ensure_notification()

    listener = RecognitionListener()
    _recognizer = SpeechRecognizer.createSpeechRecognizer(service)
    _recognizer.setRecognitionListener(listener)

    _recognizer_intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
    _recognizer_intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
    _recognizer_intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "hi-IN")

    _start_listening()


main()
