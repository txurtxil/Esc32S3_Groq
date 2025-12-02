import os
import json
import wave
import time
import logging
import struct
import io
import subprocess
import asyncio
import audioop
import math
from flask import Flask, render_template_string, request, jsonify
from flask_sock import Sock
from groq import Groq
import edge_tts

# Intentar importar opuslib para la codificación
try:
    import opuslib
except ImportError:
    print("❌ ADVERTENCIA: 'opuslib' no está instalado. Ejecuta: pip install opuslib")
    opuslib = None

# --- CONFIGURACIÓN POR DEFECTO ---
CONFIG_FILE = 'config.json'
DEFAULT_CONFIG = {
    "groq_api_key": "gsk_---------",
    "system_prompt": "Eres Xiaozhi, un asistente útil y breve.",
    "model": "llama-3.3-70b-versatile",
    "voice": "es-ES-AlvaroNeural",
    "tts_rate": "+0%",          
    "mic_gain": 1.0,           
    "silence_threshold": 1000,
    "silence_duration": 2.0,
    "chunk_size": 3200,         
    "llm_temperature": 0.7
}

GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "gemma2-9b-it"
]

# --- OPCIONES DE VOZ (NUEVO) ---
# Formato: "ID_Edge_TTS": "Nombre legible"
VOICE_OPTIONS = {
    "es-ES-AlvaroNeural": "🇪🇸 Álvaro (Hombre - España)",
    "es-ES-ElviraNeural": "🇪🇸 Elvira (Mujer - España)",
    "es-MX-DaliaNeural": "🇲🇽 Dalia (Mujer - México)",
    "es-MX-JorgeNeural": "🇲🇽 Jorge (Hombre - México)",
    "es-AR-TomasNeural": "🇦🇷 Tomás (Hombre - Argentina)",
    "es-CO-SalomeNeural": "🇨🇴 Salomé (Mujer - Colombia)",
    "en-US-ChristopherNeural": "🇺🇸 Christopher (Hombre - Inglés)",
    "en-US-AriaNeural": "🇺🇸 Aria (Mujer - Inglés)"
}

# AUDIO ROBOT
INPUT_RATE = 16000
INPUT_CHANNELS = 1
OUTPUT_RATE = 16000
OUTPUT_CHANNELS = 1
FRAME_SIZE = 960 # Frame size para decodificación (entrada)

# LOGGING
web_logs = []
def log_msg(msg):
    print(msg)
    timestamp = time.strftime("%H:%M:%S")
    web_logs.append(f"[{timestamp}] {msg}")
    if len(web_logs) > 50: web_logs.pop(0)

app = Flask(__name__)
sock = Sock(app)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except: pass
    return DEFAULT_CONFIG.copy()

def save_config(new_config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(new_config, f, indent=4)

config = load_config()

# --- PROCESAMIENTO DE AUDIO ---
def amplify_audio(pcm_data, factor):
    """Amplifica el volumen del PCM crudo usando audioop"""
    if factor == 1.0: return pcm_data
    try:
        return audioop.mul(pcm_data, 2, factor) 
    except: return pcm_data

# --- MOTORES IA ---
def process_full_interaction(pcm_data, ws):
    # 1. Amplificar audio si es necesario (Mejora STT)
    if config.get('mic_gain', 1.0) != 1.0:
        pcm_data = amplify_audio(pcm_data, config['mic_gain'])
        log_msg(f"🔊 Audio amplificado x{config['mic_gain']}")

    log_msg(f"🧠 Procesando ({len(pcm_data)} bytes)...")
    if len(pcm_data) < 4000: return

    # 2. STT
    try:
        if not config['groq_api_key']:
            log_msg("❌ Falta API Key")
            return

        client = Groq(api_key=config['groq_api_key'])
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wf:
            wf.setnchannels(INPUT_CHANNELS); wf.setsampwidth(2);
            wf.setframerate(INPUT_RATE)
            wf.writeframes(pcm_data)
        wav_buffer.seek(0)
        
        try: ws.send(json.dumps({"type": "state", "state": "processing", "text": "Escuchando..."}))
        except: pass

        transcription = client.audio.transcriptions.create(
            file=("input.wav", wav_buffer.read()),
            model="whisper-large-v3-turbo", language="es",
            prompt="Responder en español." 
        )
        user_text = transcription.text
        log_msg(f"🗣️ TÚ: {user_text}")
        
        try: ws.send(json.dumps({"type": "state", "state": "processing", "text": user_text}))
        except: pass
        
    except Exception as e:
        log_msg(f"❌ Error STT: {e}")
        return

    # 3. LLM
    try:
        completion = client.chat.completions.create(
            model=config['model'],
            messages=[{"role": "system", "content": config['system_prompt']}, {"role": "user", "content": user_text}],
            temperature=config.get('llm_temperature', 0.7)
        )
        ai_response = completion.choices[0].message.content
        log_msg(f"🤖 IA: {ai_response}")
        try: ws.send(json.dumps({"type": "state", "state": "processing", "text": ai_response[:20]+'..'}))
        except: pass
    except: return

    # 4. TTS (MODIFICADO PARA ENVIAR OPUS)
    try:
        log_msg(f"--> Generando voz ({config['voice']})...")
        pcm_audio = asyncio.run(generate_tts_pcm(ai_response))
        
        if pcm_audio:
            log_msg(f"🔊 Enviando audio ({len(pcm_audio)} bytes)...")
            ws.send(json.dumps({"type": "tts", "state": "start"}))
            
            # --- CODIFICACIÓN OPUS ---
            if opuslib:
                # Inicializar encoder: 16kHz, 1 canal, VOIP
                encoder = opuslib.Encoder(OUTPUT_RATE, OUTPUT_CHANNELS, opuslib.APPLICATION_VOIP)
                
                # Definir tamaño de frame Opus (muestras)
                # 960 muestras = 60ms a 16kHz. 
                OPUS_FRAME_SAMPLES = 960
                PCM_CHUNK_BYTES = OPUS_FRAME_SAMPLES * 2 
                
                for i in range(0, len(pcm_audio), PCM_CHUNK_BYTES):
                    chunk = pcm_audio[i:i+PCM_CHUNK_BYTES]
                    
                    # Rellenar con ceros si el último trozo es incompleto
                    if len(chunk) < PCM_CHUNK_BYTES:
                        chunk += b'\x00' * (PCM_CHUNK_BYTES - len(chunk))
                    
                    try:
                        # Codificar PCM -> Opus
                        encoded_packet = encoder.encode(chunk, OPUS_FRAME_SAMPLES)
                        ws.send(encoded_packet)
                        
                        # Esperar aprox. la duración del audio (60ms) para no saturar
                        time.sleep(0.058) 
                    except Exception as opus_err:
                        print(f"Error encode: {opus_err}")
            else:
                log_msg("❌ ERROR CRÍTICO: No se puede enviar audio. Instala 'opuslib'.")

            ws.send(json.dumps({"type": "tts", "state": "stop"}))
            log_msg("✅ Fin.")
    except Exception as e:
        log_msg(f"❌ Error TTS: {e}")

async def generate_tts_pcm(text):
    # Aplicar velocidad de voz
    rate = config.get('tts_rate', '+0%')
    voice = config.get('voice', 'es-ES-AlvaroNeural') # Obtener voz de la config
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    
    mp3_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio": mp3_data += chunk["data"]
    
    # Convertir MP3 a PCM raw (s16le, 16000Hz, mono)
    try:
        cmd = ["ffmpeg", "-y", "-i", "pipe:0", "-f", "s16le", "-acodec", "pcm_s16le", "-ar", str(OUTPUT_RATE), "-ac", "1", "pipe:1"]
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        pcm_data, _ = process.communicate(input=mp3_data)
        return pcm_data
    except: return b""

def get_volume(pcm_chunk):
    try:
        count = len(pcm_chunk) // 2
        shorts = struct.unpack(f"{count}h", pcm_chunk)
        sum_squares = sum(n * n for n in shorts)
        return int(math.sqrt(sum_squares / count))
    except: return 0

# --- INTERFAZ WEB AVANZADA ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎛️ Xiaozhi V8 Panel (Voz Selector)</title>
    <style>
        body { background: #121212; color: #ddd; font-family: sans-serif; padding: 10px; margin: 0; }
        .container { max-width: 800px; margin: 0 auto; }
        .card { background: #1e1e1e; border-radius: 8px; padding: 15px; margin-bottom: 15px; border: 1px solid #333; }
        h3 { margin-top: 0; color: #bb86fc; border-bottom: 1px solid #444; padding-bottom: 5px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        label { display: block; margin-top: 8px; font-size: 0.9em; color: #03dac6; }
        input, select, textarea { width: 100%; background: #2c2c2c; border: 1px solid #555; color: #fff; padding: 8px; box-sizing: border-box; border-radius: 4px; }
        button { width: 100%; padding: 12px; background: #3700b3; color: white; border: none; border-radius: 4px; font-weight: bold; cursor: pointer; margin-top: 15px; }
        #console { background: #000; height: 250px; overflow-y: auto; padding: 10px; font-family: monospace; font-size: 12px; color: #0f0; border-radius: 4px; }
        .range-val { float: right; color: #fff; }
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <h3>⚙️ Configuración Avanzada</h3>
            <form id="configForm">
                <div class="grid">
                    <div>
                        <label>🧠 Modelo LLM</label>
                        <select name="model">
                            {% for model in models %}
                            <option value="{{ model }}" {% if config.model == model %}selected{% endif %}>{{ model }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div>
                        <label>🗣️ Voz (Personaje)</label>
                        <select name="voice">
                            {% for v_id, v_name in voices.items() %}
                            <option value="{{ v_id }}" {% if config.voice == v_id %}selected{% endif %}>{{ v_name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                </div>

                <label>🎭 Prompt del Sistema</label>
                <textarea name="system_prompt" rows="2">{{ config.system_prompt }}</textarea>

                <div class="grid">
                    <div>
                        <label>🔕 Umbral Silencio</label>
                        <input type="number" name="silence_threshold" value="{{ config.silence_threshold }}">
                    </div>
                    <div>
                        <label>⏱️ Espera Silencio (s)</label>
                        <input type="number" name="silence_duration" step="0.1" value="{{ config.silence_duration }}">
                    </div>
                </div>

                <div class="grid">
                    <div>
                        <label>🎤 Ganancia Micro (x): <span id="gain_val" class="range-val">{{ config.mic_gain }}</span></label>
                        <input type="range" name="mic_gain" min="0.5" max="5.0" step="0.1" value="{{ config.mic_gain }}" oninput="document.getElementById('gain_val').innerText=this.value">
                    </div>
                    <div>
                        <label>⏩ Velocidad Voz</label>
                        <select name="tts_rate">
                            <option value="-20%" {% if config.tts_rate == '-20%' %}selected{% endif %}>Lenta (-20%)</option>
                            <option value="+0%" {% if config.tts_rate == '+0%' %}selected{% endif %}>Normal</option>
                            <option value="+20%" {% if config.tts_rate == '+20%' %}selected{% endif %}>Rápida (+20%)</option>
                        </select>
                    </div>
                </div>

                 <div class="grid">
                    <div>
                         <label>🌡️ Creatividad (Temp)</label>
                         <input type="range" name="llm_temperature" min="0" max="1" step="0.1" value="{{ config.llm_temperature }}">
                    </div>
                    <div>
                        <label>🔑 API Key</label>
                        <input type="password" name="groq_api_key" value="{{ config.groq_api_key }}">
                    </div>
                </div>

                <button type="submit">💾 GUARDAR Y APLICAR</button>
            </form>
        </div>

        <div class="card">
            <h3>🖥️ Monitor en Vivo</h3>
            <div id="console">Conectando...</div>
        </div>
    </div>

    <script>
        document.getElementById('configForm').onsubmit = function(e) {
            e.preventDefault();
            const fd = new FormData(this);
            fetch('/save_config', { method: 'POST', body: fd })
                .then(r => r.json())
                .then(data => alert('✅ Configuración actualizada!'));
        };

        setInterval(() => {
            fetch('/get_logs').then(r => r.json()).then(d => {
                const c = document.getElementById('console');
                const html = d.logs.map(l => `<div>${l}</div>`).join('');
                if (c.innerHTML !== html) { c.innerHTML = html; c.scrollTop = c.scrollHeight; }
            });
        }, 1000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    c = config.copy()
    c.setdefault('mic_gain', 1.0)
    c.setdefault('tts_rate', '+0%')
    c.setdefault('chunk_size', 3200)
    c.setdefault('llm_temperature', 0.7)
    c.setdefault('voice', 'es-ES-AlvaroNeural')
    # Pasamos también la lista de voces a la plantilla
    return render_template_string(HTML_TEMPLATE, config=c, models=GROQ_MODELS, voices=VOICE_OPTIONS)

@app.route('/save_config', methods=['POST'])
def save_conf():
    global config
    config.update({
        "groq_api_key": request.form.get('groq_api_key'),
        "system_prompt": request.form.get('system_prompt'),
        "model": request.form.get('model'),
        # Ahora leemos la voz del formulario
        "voice": request.form.get('voice'), 
        "silence_threshold": int(request.form.get('silence_threshold')),
        "silence_duration": float(request.form.get('silence_duration')),
        "mic_gain": float(request.form.get('mic_gain')),
        "tts_rate": request.form.get('tts_rate'),
        "chunk_size": 3200, 
        "llm_temperature": float(request.form.get('llm_temperature'))
    })
    save_config(config)
    log_msg(f"⚙️ Configuración guardada. Voz actual: {config['voice']}")
    return jsonify({"status": "ok"})

@app.route('/get_logs')
def get_logs(): return jsonify({"logs": web_logs})

# --- WEBSOCKET ---
@sock.route('/ws')
def websocket_handler(ws):
    log_msg("🔌 ROBOT CONECTADO")
    
    decoder = None
    if opuslib:
        try:
            decoder = opuslib.Decoder(INPUT_RATE, INPUT_CHANNELS)
        except Exception as e:
            log_msg(f"Error decoder init: {e}")
    
    pcm_buffer = b""
    is_recording = False
    last_speech_time = 0
    start_record_time = 0
    
    try:
        while True:
            data = ws.receive()
            if isinstance(data, str):
                msg = json.loads(data)
                if msg.get('type') == 'hello':
                    ws.send(json.dumps({
                        "type": "hello", 
                        "transport": "websocket", 
                        "audio_params": {
                            "format": "opus", 
                            "sample_rate": 16000, 
                            "channels": 1,
                            "frame_duration": 60 
                        }
                    }))
                    log_msg("🤝 Handshake OK (Modo OPUS)")

                if msg.get('type') == 'listen' and msg.get('state') == 'start':
                    log_msg("▶️ ESCUCHANDO...")
                    pcm_buffer = b""
                    is_recording = True
                    start_record_time = time.time()
                    last_speech_time = time.time()
                    if decoder: 
                        try: decoder.reset_state()
                        except: pass

            elif isinstance(data, bytes):
                if is_recording:
                    try:
                        if decoder: 
                            try:
                                pcm_chunk = decoder.decode(data, FRAME_SIZE)
                            except:
                                pcm_chunk = b'\x00' * 320
                        else: 
                            pcm_chunk = data
                        
                        pcm_buffer += pcm_chunk
                        vol = get_volume(pcm_chunk)
                        
                        if vol > config['silence_threshold']:
                            last_speech_time = time.time()
                        
                        if (time.time() - last_speech_time) > config['silence_duration'] and (time.time() - start_record_time) > 2.0:
                            log_msg("⏹️ Silencio detectado.")
                            is_recording = False
                            ws.send(json.dumps({"type": "tts", "state": "stop"}))
                            process_full_interaction(pcm_buffer, ws)
                            pcm_buffer = b""

                    except Exception as e: pass

    except Exception as e:
        log_msg(f"❌ Desconexión: {e}")

if __name__ == '__main__':
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        print("\n❌❌ ERROR: FFMPEG no está instalado o no está en el PATH. El audio no funcionará.\n")

    app.run(host='0.0.0.0', port=8000, threaded=True)
