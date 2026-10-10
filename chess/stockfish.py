import time
import zmq
import chess
import chess.engine

#config zeromq

context_machine = zmq.Context()

# receives the context from the state machine, to know when to transcribe
subscriber_machine = context_machine.socket(zmq.SUB)
subscriber_machine.connect("ipc:///tmp/state_machine.ipc")
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'MODEL_THINKING')

#send the command/movement to a verifier 
context_move = zmq.Context()
subscriber_move = context_move.socket(zmq.PUB)
subscriber_move.bind("ipc:///tmp/movement.ipc")

# --- Config Stockfish
STOCKFISH_PATH = "/usr/games/stockfish"

def calcular_melhor_jogada(fen_string: str, time_limit: float = 0.5) -> str:
    board = chess.Board(fen_string)
        #get a play result in 0.5 sec so its not to slow
    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine: 
        result = engine.play(board, chess.engine.Limit(time=time_limit))
        return result.move.uci()

# main loop
print("Starting stockfish...")

while True:
    try:
        # Recieves message in the format: "MODEL_THINKING <FEN_DA_POSICAO>"
        message = subscriber_machine.recv_string()
        
        # Split here separetes the real fen message from the rest
        topic, fen = message.split(" ", 1)
        
        print(f"Received for the fen: {fen}")
        
        # Stockfish calculating
        best_move_uci = calcular_melhor_jogada(fen, time_limit=0.5)
        print(f"The chosen play was: {best_move_uci}")
        
        #Sends the chosen play via zeromq socket
        subscriber_move.send_string(f"ENGINE_MOVE {best_move_uci}")

    except ValueError:
        # If the message does not have two parts returns erros, because the engine needs both the board situation and command
        print("[ENGINE ERRO] Message not in format. Expected: 'MODEL_THINKING <FEN>'")
    except Exception as e:
        print(f"[ENGINE ERRO]: {e}")
        time.sleep(0.1)