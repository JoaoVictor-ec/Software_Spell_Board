import os
import re
import time
import unicodedata
import zmq
import chess

# Maps writen numbers to numerals
NUM_MAP = {
    'one': '1',
    'two': '2', 'to': '2', 'too': '2',
    'three': '3',
    'four': '4', 'for': '4',
    'five': '5',
    'six': '6',
    'seven': '7',
    'eight': '8', 'ate': '8'
}

# Discart of comun words, can add more the more we use
NOISE_WORDS = ['to', 'at', 'goes', 'takes', 'captures', 'on', 'in', 'move', 'please', 'the']


#clear whiper to facilitate cordinates search
def clean_speech_text(text: str) -> str:
    text = text.lower().strip()
    
    # removes accent
    text = ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'MN')
    
    # removes ponctuations
    text = re.sub(r'[^\w\s]', '', text)
    
    # swap the writen numbers to the numerals
    words = text.split()
    cleaned_words = [NUM_MAP.get(w, w) for w in words]
    text = " ".join(cleaned_words)
    
    # Remove noise words declared above
    for word in NOISE_WORDS:
        text = re.sub(r'\b' + word + r'\b', '', text)
        
    return ' '.join(text.split())

#compares the legal movements, with what was recieved and then return it in the UCI protocol
def parse_speech_to_uci(speech_text: str, board: chess.Board) -> str | None:

    text = clean_speech_text(speech_text)
    
    # Special treatment for castling
    if "short castle" in text or "kingside castle" in text or text == "castle":
        if chess.Move.from_uci("e1g1") in board.legal_moves: return "e1g1"
        if chess.Move.from_uci("e8g8") in board.legal_moves: return "e8g8"
    elif "long castle" in text or "queenside castle" in text:
        if chess.Move.from_uci("e1c1") in board.legal_moves: return "e1c1"
        if chess.Move.from_uci("e8c8") in board.legal_moves: return "e8c8"

    # Search the command in the transcribed text
    found_squares = re.findall(r'[a-h][1-8]', text)
    if len(found_squares) == 2:
        possible_uci = f"{found_squares[0]}{found_squares[1]}"
        try:
            move = chess.Move.from_uci(possible_uci)
            if move in board.legal_moves:
                return move.uci()
        except ValueError:
            pass

    # Validate legal plays
    for move in board.legal_moves:
        uci = move.uci()               # Ex: "g1f3", "e2e4"
        san = board.san(move)           # Ex: "Nf3", "e4", "Bxc4"
        
        dest_match = re.search(r'([a-h][1-8])', san)
        if not dest_match:
            continue
        dest_square = dest_match.group(1) # Ex: "f3", "e4"
        
        piece_symbol = san[0] if san[0] in ['N', 'B', 'R', 'Q', 'K'] else ''
        
        # possible phrases of plays
        possible_phrases = []
        if piece_symbol == 'N':
            possible_phrases.extend([f"knight {dest_square}", f"night {dest_square}", f"knight on {dest_square}"])
        elif piece_symbol == 'B':
            possible_phrases.extend([f"bishop {dest_square}", f"bishop on {dest_square}"])
        elif piece_symbol == 'R':
            possible_phrases.extend([f"rook {dest_square}", f"rook on {dest_square}"])
        elif piece_symbol == 'Q':
            possible_phrases.extend([f"queen {dest_square}"])
        elif piece_symbol == 'K':
            possible_phrases.extend([f"king {dest_square}"])
        else:
            possible_phrases.extend([dest_square, f"pawn {dest_square}"])

        possible_phrases.append(uci)
        possible_phrases.append(f"{uci[:2]} {uci[2:]}") # Ex: "g1 f3"

        #if any command is on the transcription identify
        for phrase in possible_phrases:
            if phrase in text:
                return uci

    return None

#zeromq sockets
context = zmq.Context()

# Recieves from the state_machine the states (PLAYER, MODEL, RESET)
sub_machine = context.socket(zmq.SUB)
sub_machine.connect("ipc:///tmp/state_machine.ipc")
sub_machine.setsockopt_string(zmq.SUBSCRIBE, 'PLAYER')
sub_machine.setsockopt_string(zmq.SUBSCRIBE, 'MODEL')
sub_machine.setsockopt_string(zmq.SUBSCRIBE, 'RESET')#???

# Receives the string from whisper
sub_player_move = context.socket(zmq.SUB)
sub_player_move.connect("ipc:///tmp/movement.ipc")
sub_player_move.setsockopt_string(zmq.SUBSCRIBE, "")

# Recieves moves from stockfish(engine)
sub_engine_move = context.socket(zmq.SUB)
sub_engine_move.connect("ipc:///tmp/engine_output.ipc")
sub_engine_move.setsockopt_string(zmq.SUBSCRIBE, "")

# Publishes the current possition of the board
pub_verified = context.socket(zmq.PUB)
pub_verified.bind("ipc:///tmp/verified_state.ipc")

# Poller manages the many sockets so the zeromq doesn't freeze
poller = zmq.Poller()
poller.register(sub_machine, zmq.POLLIN)
poller.register(sub_player_move, zmq.POLLIN)
poller.register(sub_engine_move, zmq.POLLIN)

#initailize the board
board = chess.Board()
current_turn = 'MODEL'  # Padronized initial state

print("Board started")
print(board)
print(f"FEN : {board.fen()}")

while True:
    try:
        # timout 100 ms between sockets
        sockets = dict(poller.poll(100))

        # State treatment
        if sub_machine in sockets:
            state_msg = sub_machine.recv_string()
            if state_msg == 'RESET':
                board.reset()
                print("Reseting the game")
                pub_verified.send_string(f"BOARD_RESET {board.fen()}")
            else:
                current_turn = state_msg
                print(f"Switching to {current_turn}s turn")

        # --- Processing players move
        if sub_player_move in sockets:
            raw_speech = sub_player_move.recv_string()
            print(f"Transcription received '{raw_speech}'")

            if current_turn == 'PLAYER':
                uci_move = parse_speech_to_uci(raw_speech, board)

                if uci_move:
                    # Executes valid move
                    move_obj = chess.Move.from_uci(uci_move)
                    board.push(move_obj)
                    
                    new_fen = board.fen()
                    print(f"Move: {uci_move}")
                    print(f"New FEN: {new_fen}")

                    #Publishes the move
                    pub_verified.send_string(f"PLAYER_MOVE {uci_move}|{new_fen}")
                    
                    # Check if it was mate
                    if board.is_game_over():
                        print(f"Check if it was mate: {board.result()}")
                        pub_verified.send_string(f"GAME_OVER {board.result()}")
                else:
                    print(f" Invalid move: '{raw_speech}'")
                    # Publishes error for the serial nodex 
                    pub_verified.send_string(f"INVALID_MOVE {raw_speech}")
            else:
                print("It isn't the players turn, so the command was ignored")

        #  processing engines move ENGINE (Stockfish) 
        if sub_engine_move in sockets:
            engine_msg = sub_engine_move.recv_string()
            print(f"engines move: '{engine_msg}'")

            if current_turn == 'MODEL':
                try:
                    _, uci_move = engine_msg.split(" ", 1)
                    move_obj = chess.Move.from_uci(uci_move)

                    if move_obj in board.legal_moves:
                        board.push(move_obj)
                        new_fen = board.fen()
                        print(f"confirming engines move {uci_move}")
                        print(f"new FEN: {new_fen}")

                        #publishes for the arduino to move and for the state machine to move on
                        pub_verified.send_string(f"ENGINE_MOVE_VALIDATED {uci_move}|{new_fen}")

                        if board.is_game_over():
                            print(f"Game end: {board.result()}")
                            pub_verified.send_string(f"GAME_OVER {board.result()}")
                    else:
                        print(f"Engine tried ilegal move: {uci_move}")
                except Exception as err:
                    print(f"ERROR: {err}")

    except Exception as e:
        print(f"Error at the verification: {e}")
        time.sleep(0.1)