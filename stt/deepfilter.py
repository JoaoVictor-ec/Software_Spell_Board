import os
import time
import zmq
from df import enhance, init_df
import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly
import onnxruntime as ort


#send filtered audio
context_a = zmq.Context()
sender_a = context_a.socket(zmq.PUSH)

sender_a.bind("ipc:///tmp/audio_filtrado.ipc")

# receives the context from the state machine, to know when to transcribe
context_machine = zmq.Context()

subscriber_machine = context_machine.socket(zmq.SUB)

subscriber_machine.connect("ipc:///tmp/state_machine.ipc")

#assing topics of state machine 
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'PLAYER')
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'MODEL')
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'RESET')

SAMPLE_RATE_IN = 48000   # DeepFilterNet (48 kHz) native freq
SAMPLE_RATE_OUT = 16000  # Whisper (16 kHz) required freq
# Frame of 100ms (4800 samples  48kHz -> 1600 samples  16kHz)
FRAME_DURATION = 0.1 
FRAME_SIZE_48K = int(SAMPLE_RATE_IN * FRAME_DURATION)


#load model
print("loading DeepFilterNet...")
df_model, df_state, _ = init_df()

current_turn = 'MODEL'   # padronized state

# Loads ONNX of Silero VAD in memorie, change path if needed
VAD_MODEL_PATH = '/home/joao/oficinas2/Spell_nodes/stt/silero_vad.onnx'
if not os.path.exists(VAD_MODEL_PATH):
    print(f"Error: Vad model not found {VAD_MODEL_PATH}")
    exit(1)
vad_session = ort.InferenceSession(VAD_MODEL_PATH)
vad_state = np.zeros((2, 1, 128), dtype=np.float32)# Estado inicial do LSTM do Silero VAD?????


#if the chance of speech passes the treshold reads audio
def is_speech_silero(audio_16k_chunk, threshold=0.5):

    global vad_state
    
    # Perpare tensors especified for Silero VAD
    inputs = {
        'input': audio_16k_chunk.reshape(1, -1).astype(np.float32),
        'state': vad_state,
        'sr': np.int64(SAMPLE_RATE_OUT)
    }
    
    outputs = vad_session.run(None, inputs)
    prob_speech = outputs[0][0][0]
    vad_state = outputs[1]  # updtae LSTM for the next frame
    
    return prob_speech > threshold

def reset_vad_state():
    #resets silero vad when frase ends or turn ends
    global vad_state
    vad_state = np.zeros((2, 1, 128), dtype=np.float32)

current_turn = 'MODEL'
speech_buffer = []          # Acumulate the 16kHz frames while player speaks
is_speaking = False         # Flag indicating its on going
silence_counter = 0         # counter for the silero frames
MAX_SILENCE_CHUNKS = 25     # ~25 frames x 32ms ≈ 800ms of silence to end detection

print("starting mic capture...")

with sd.InputStream(samplerate=SAMPLE_RATE_IN, channels=1, dtype='float32', blocksize=FRAME_SIZE_48K) as stream: #config mic i/o here
    while True:
        # Check turn
        try:
            current_turn = subscriber_machine.recv_string(flags=zmq.NOBLOCK)
            print(f"{current_turn} turn to play")
            if current_turn != 'PLAYER':
                speech_buffer.clear()
                is_speaking = False
                reset_vad_state()
        except zmq.Again:
            pass

        try:
            #Always reads the mic
            frame_48k, overflow = stream.read(FRAME_SIZE_48K)
            
            # process the filtered audio only if it is the players turn
            if current_turn == 'PLAYER':
                audio_48k = frame_48k.flatten()

                # filter via deepfilternet
                audio_limpo_48k = enhance(df_model, df_state, audio_48k)

                #  Downsampling to 16kHz (1536 -> 512 amostras)
                audio_16k = resample_poly(audio_limpo_48k, up=1, down=3).astype(np.float32)

                #  Avaliation using Silero VAD via ONNX
                speech_detected = is_speech_silero(audio_16k)

                if speech_detected:
                    if not is_speaking:
                        print("Voice detected...")
                        is_speaking = True
                    
                    speech_buffer.append(audio_16k)
                    silence_counter = 0

                elif is_speaking:
                    # Acumulates the silent parts between words
                    speech_buffer.append(audio_16k)
                    silence_counter += 1

                    # if hit 800ms of silence, isn't speeking anymore
                    if silence_counter >= MAX_SILENCE_CHUNKS:
                        print("No more speech ending transcription...")
                        
                        full_audio = np.concatenate(speech_buffer)
                        sender_a.send(full_audio.tobytes())

                        # Reset the buffer and state of VAD
                        speech_buffer.clear()
                        is_speaking = False
                        silence_counter = 0
                        reset_vad_state()

        except Exception as e:
            print(f"Error of audio: {e}")