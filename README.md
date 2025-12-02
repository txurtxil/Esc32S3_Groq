# 🤖 Xiaozhi ESP32-S3 (Spotpear Edition) - Local Server

![Status](https://img.shields.io/badge/Status-Working-success)
![Hardware](https://img.shields.io/badge/Hardware-Spotpear_ESP32_S3-blue)
![Backend](https://img.shields.io/badge/Backend-Python_Flask-yellow)

Este proyecto es una modificación del firmware **Xiaozhi (v2.0.5)** adaptado específicamente para la placa **Spotpear ESP32-S3 1.28" Box**.

El objetivo principal de este fork es **eliminar la dependencia de la nube china y MQTT**, permitiendo que el robot funcione con un **servidor local (Python)**. Utiliza **Groq (Llama 3)** para la inteligencia y **Edge-TTS** para la voz, logrando una latencia mínima y conversaciones fluidas en español.

## ✨ Características
* **Hardware:** Soporte nativo para Spotpear ESP32-S3 1.28 (pantalla redonda).
* **Protocolo:** WebSocket directo (sin MQTT).
* **Audio:** Soporte optimizado para OPUS y PCM.
* **IA (LLM):** Llama 3.3 70B (vía Groq API).
* **Voz (TTS):** Microsoft Edge TTS (Español Natural).
* **Hacks Incluidos:** * Parches de compilación para ESP-IDF 5.4.2.
    * Bypass de autenticación de tokens.
    * Configuración de idioma español forzada.

---

## 🛠️ Requisitos

### Hardware
* Placa de desarrollo **Spotpear ESP32-S3 1.28 Box**.

### Software
* **ESP-IDF v5.4.2** (Instalación Offline recomendada).
* **Python 3.10+** (Para el servidor).
* **FFmpeg**: Necesario instalarlo y agregarlo al PATH del sistema (Windows/Linux) para la conversión de audio.

---

## 🚀 Guía de Instalación (Firmware)

Este firmware ha sido modificado para compilarse sin errores en las versiones modernas de IDF.

### 1. Configuración de tu IP Local
Antes de compilar, debes decirle al robot dónde está tu servidor Python.
1.  Abre el archivo: `main/protocols/websocket_protocol.cc`
2.  Busca la línea (aprox 84):
    ```cpp
    std::string url = "ws://192.168.1.175:8000/ws";
    ```
3.  **Cambia `192.168.1.175` por la IP local de tu ordenador.**

### 2. Compilación y Flasheo
Abre la terminal de **ESP-IDF 5.4 PowerShell** y navega a la carpeta del proyecto.

```powershell
# 1. Limpieza inicial (opcional pero recomendada)
idf.py fullclean

# 2. Configurar el target
idf.py set-target esp32s3

# 3. WORKAROUND CRÍTICO: Crear asset dummy
# El sistema de build falla si este archivo no existe previamente.
cd build
New-Item -Path . -Name "generated_assets.bin" -ItemType "file" -Force
cd ..

# 4. Configurar opciones (Solo verificar que está en Spotpear y Español)
idf.py menuconfig

# 5. Compilar y Subir
# Asegúrate de saber en qué puerto está tu placa (ej. COM3)
idf.py -p COM3 erase_flash    # Solo la primera vez
idf.py -p COM3 flash monitor

🐍 Guía de Instalación (Servidor)
El "cerebro" corre en tu PC. Asegúrate de tener FFmpeg instalado antes de seguir.
1. Instalar Dependencias
Ejecuta esto en tu terminal para instalar las librerías de Python necesarias:pip
pip install flask flask-sock groq edge-tts opuslib


(Nota: Si usas Windows, opuslib suele funcionar directo. En Linux podrías necesitar instalar libopus-dev).
2. Configuración del Servidor (server.py)
Abre el archivo server.py (o 01final.py) y edita la configuración inicial:

DEFAULT_CONFIG = {
    "groq_api_key": "gsk_PON_AQUI_TU_API_KEY_DE_GROQ",
    "system_prompt": "Eres Xiaozhi, un asistente útil y breve.",
    "model": "llama-3.3-70b-versatile",
    ...
}

Consigue tu API Key gratis en Groq Console.
3. Ejecutar
python server.py

Verás un mensaje indicando que el servidor corre en el puerto 8000.
📶 Primer Uso
Con el servidor Python corriendo, enciende el ESP32.

Si es la primera vez, el ESP32 creará un Punto de Acceso WiFi (Hotspot).
Conéctate a ese WiFi con tu móvil y configura los datos de tu router (SSID y Contraseña).
El ESP32 se reiniciará, se conectará a tu WiFi y luego buscará el servidor WebSocket.

Consola Python: Deberías ver 🔌 ROBOT CONECTADO.
Uso: Pulsa el botón "BOOT" (o toca la pantalla táctil) para hablar.

🐞 Solución de Problemas Comunes
Error lang_config.h: Si al compilar dice que falta este archivo, verifica que existe en main/assets/lang_config.h. Este repo ya debería incluir el parche manual.
El robot no habla (pero hay texto): Verifica que tienes FFmpeg instalado y accesible desde la terminal (ffmpeg -version).

Error de compilación format %x: Se ha aplicado un parche en image_to_jpeg.cpp y en CMakeLists.txt para ignorar estos errores en compiladores nuevos.

subo en firmware firmware_xiaozhi_completo.bin listo para apuntar a la IP privada 192.168.1.175 que es donde devera fucionar server.py
flasheable desde https://espressif.github.io/esptool-js/

⚖️ Créditos y Licencia
Basado en el trabajo original de Xiaozhi ESP32.

Modificaciones realizadas para hardware Spotpear y uso educativo local.
