import zmq
from pywhispercpp.model import Model
import os
import time
import numpy as np

#initialization of zeroMQ functions needed in the whisper node

#Receives filtered audio
context_a = zmq.Context()
receiver_a = context_a.socket(zmq.PULL)

receiver_a.connect("ipc:///tmp/audio_filtrado.ipc")

# receives the context from the state machine, to know when to transcribe
context_machine = zmq.Context()

subscriber_machine = context_machine.socket(zmq.SUB)

subscriber_machine.connect("ipc:///tmp/state_machine.ipc")

#send the command/movement to a verifier
context_move = zmq.Context()

subscriber_move = context_move.socket(zmq.PUB)

subscriber_move.bind("ipc:///tmp/movement.ipc")

# Register Poller
poller = zmq.Poller()
poller.register(subscriber_machine, zmq.POLLIN)
poller.register(receiver_a, zmq.POLLIN)                                                                                                                                                                                                                                                                                             

#assing topics of state machine 
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'PLAYER')
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'MODEL')
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'RESET')


print("Loading whisper base model")

MODEL_PATH = '/home/joao/oficinas2/Spell_nodes/stt/whisper.cpp/models/ggml-base.en.bin'

def load_model_whisper(model_path):
    #checks for the existence of the model path
    if not os.path.exists(model_path):
        print(f"model path not found in {model_path}")
        return None
    
    print("... lading ...")
    start_time = time.time()

    try:
        # Loads local whisper model, change path if needed, use 4 cores(all that the rpi has)
        model = Model(
            model_path, 
            n_threads=4,          
            print_realtime=False, 
        )
        end_time = time.time() - start_time 
        print(f"stt ready to transcribe, waiting for audio...loaded in {end_time:.2f} seconds")
        return model
    except Exception as e:
        print("could not load model, dying......")
        return None    

def transcribe(whisper_model, audio_bytes):
    #converts the received bytes from zeroMQ to a float array
    audio_array = np.frombuffer(audio_bytes, dtype=np.float32)
    #use model to transcribe parts of the audio
    segments = whisper_model.transcribe(audio_array)
    #unite the parts transcribed
    text = "".join([segment.text for segment in segments]).strip()
    return text

whiper_model = load_model_whisper(MODEL_PATH)

#if that check if model was loaded
if whiper_model is None:
    print("model not loaded ?!?")
    exit(1)

current_turn = 'MODEL' # Estado inicial

while True:
    try:
        # Pller wits for 100 ms so the loop don't get stuck
        sockets = dict(poller.poll(100))

        # Sees if there was a state change at the state machine
        if subscriber_machine in sockets:
            state_msg = subscriber_machine.recv_string()
            
            # Garantees that the current state is saved
            current_turn = state_msg.split(" ")[0] 
            print(f"its {current_turn} to play")

            if current_turn == 'RESET':
                print("Game reseted")
                # If there is any audio in the line, when the reset is activated, it ignores

        # Verifies if the audio from deepfilter is arriving
        if receiver_a in sockets:
            audio_bytes = receiver_a.recv()
            
            # Transcribe only when it is the players turn
            if current_turn == 'PLAYER':
                command = transcribe(whiper_model, audio_bytes)
                print(f"command: {command}")
                subscriber_move.send_string(command)
            else:
                pass 

    except Exception as e:
        print(f"error in audio processing: {e}")
        time.sleep(0.1)