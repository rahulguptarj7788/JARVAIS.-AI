[app]
title = Jarvis AI
package.name = jarvisai
package.domain = com.jarvis.assistant
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,xml,json,java
source.include_patterns = assets/*,*.xml
version = 1.0.0
requirements = python3==3.10.12,kivy==2.3.0,requests,urllib3,certifi,pyjnius,edge-tts,onnxruntime
orientation = portrait
fullscreen = 0
android.permissions = RECORD_AUDIO, FOREGROUND_SERVICE, FOREGROUND_SERVICE_MICROPHONE, SYSTEM_ALERT_WINDOW, POST_NOTIFICATIONS, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, BIND_ACCESSIBILITY_SERVICE
android.api = 33
android.minapi = 24
android.ndk = 25b
android.private_storage = True
android.androidx = True
android.add_src = java
android.services = JarvisWakewordService:services.py, JarvisWatchdogService:services.py

[buildozer]
log_level = 2
warn_on_root = 1

