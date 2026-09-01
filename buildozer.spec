[app]
title = Jarvis AI
package.name = jarvisai
package.domain = com.jarvis.assistant
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,xml,json,java
source.include_patterns = assets/*,*.xml
version = 1.0.0
requirements = hostpython3==3.11.6,python3==3.11.6,kivy,requests,urllib3,certifi,pyjnius
orientation = portrait
fullscreen = 0
android.permissions = RECORD_AUDIO, FOREGROUND_SERVICE, FOREGROUND_SERVICE_MICROPHONE, SYSTEM_ALERT_WINDOW, POST_NOTIFICATIONS, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE
android.api = 33
android.build_tools = 33.0.2
android.minapi = 24
android.ndk = 25b
android.sdk_path = /usr/local/lib/android/sdk
android.ndk_path = /usr/local/lib/android/sdk/ndk/25.2.9519653
android.private_storage = True
android.androidx = True

[buildozer]
log_level = 2
warn_on_root = 1
android.accept_sdk_licenses = True
