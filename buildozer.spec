[app]

# (str) Title of your application
title = Jarvis AI

# (str) Package name
package.name = jarvisai

# (str) Package domain (needed for android packaging)
package.domain = com.jarvis.assistant

# (str) Source code where the main.py lives
source.dir = .

# (list) Source files to include
source.include_exts = py,png,jpg,kv,atlas,xml,json

# (list) List of inclusions using pattern matching
source.include_patterns = assets/*,*.xml

# (str) Application versioning
version = 1.0.0

# (list) Application requirements
requirements = python3,kivy==2.3.0,requests,urllib3,certifi,pyjnius

# (str) Supported orientation
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (list) Permissions
android.permissions = RECORD_AUDIO, FOREGROUND_SERVICE, FOREGROUND_SERVICE_MICROPHONE, SYSTEM_ALERT_WINDOW, POST_NOTIFICATIONS, ACCESS_NOTIFICATION_POLICY, READ_PHONE_STATE, READ_CALL_LOG, ANSWER_PHONE_CALLS, MODIFY_AUDIO_SETTINGS, REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, QUERY_ALL_PACKAGES, INTERNET, ACCESS_NETWORK_STATE

# (int) Target Android API level
android.api = 33

# (int) Minimum API level supported
android.minapi = 24

# (str) Android NDK version
android.ndk = 25b

# (bool) Use --private data dir (true) or --dir public storage (false)
android.private_storage = True

# (bool) Enable AndroidX support
android.androidx = True

# (list) Services to declare
android.services = JarvisWakeWordService:services.py, JarvisWatchdogService:services.py

[buildozer]

# (int) Log level
log_level = 2

# (int) Display warning if buildozer is run as root
warn_on_root = 1

