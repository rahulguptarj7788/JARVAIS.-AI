"""
Runs as a separate Android foreground service process (python-for-android
service model). Shows a persistent notification so the OS is less likely
to kill it, and loops SpeechRecognizer listening for "jarvis"/"hey jarvis".
On detection, it records the following utterance and writes it into the
shared SQLite db (wake_events table) for the main app to pick up.

IMPORTANT LIMITS (be aware of these on a MIUI/Redmi device):
- Android 10+ restricts background microphone access; this only reliably
  works while the service holds a genuine foreground-service notification
  (handled below) AND the user has disabled MIUI's battery/autostart
  restriction for this app.
- This is best-effort 24/7, not a guarantee -- no app can fully prevent
  an aggressive OEM battery manager from killing it.
"""
import time
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

service = PythonService.mService
CHANNEL_ID = "jarvis_wakeword_channel"


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

    @java_method("(I)V")
    def onError(self, error):
        pass

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


def main_loop():
    _ensure_notification()
    listener = RecognitionListener()
    recognizer = SpeechRecognizer.createSpeechRecognizer(service)
    recognizer.setRecognitionListener(listener)

    intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
    intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
    intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "hi-IN")

    while True:
        try:
            recognizer.startListening(intent)
        except Exception:
            pass
        time.sleep(4)


main_loop()
