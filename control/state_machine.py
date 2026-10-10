import time
import zmq

def main():
    context = zmq.Context()

    # Publishes states for the other nodes
    # Published topics: 'PLAYER', 'MODEL_THINKING <FEN>', 'RESET', 'ROBOT_MOVING'
    pub_state = context.socket(zmq.PUB)
    pub_state.bind("ipc:///tmp/state_machine.ipc")

    # Listen to the verifier and serial node
    sub_verified = context.socket(zmq.SUB)
    sub_verified.connect("ipc:///tmp/verified_state.ipc")
    # Subscribe the events gotten from verifier and serial
    sub_verified.setsockopt_string(zmq.SUBSCRIBE, "")

    print("Orquestrador iniciado. Aguardando estabilização das conexões IPC...")
    time.sleep(2)  # Time for the zeromq sockets to connect

    # Inicial state, for now we assume the player is always playing with the white pieces
    current_state = "PLAYER"
    print(f"\nStarting match, now its: {current_state} turn to play")
    pub_state.send_string(current_state)

    while True:
        try:
            # Receives the message from the verifier or serial node
            msg = sub_verified.recv_string()
            print(f"\nEvent received: {msg}")

            if msg.startswith("PLAYER_MOVE"):
                # If the human move was valid, goes to the stockfishes turn
                _, data = msg.split(" ", 1)
                uci_move, fen = data.split("|")
                print(f"Human move alright ({uci_move})")
                
                # Stockfish turn, so its changing state
                current_state = f"MODEL_THINKING {fen}"
                print(f"Changing state to: {current_state}")
                pub_state.send_string(current_state)

            elif msg.startswith("INVALID_MOVE"):
                # player made ilegal move, maintain its turn
                print("Invalid move, player tries again")
                current_state = "PLAYER"
                pub_state.send_string(current_state)

            elif msg.startswith("ENGINE_MOVE_VALIDATED"):
                # Engines move processed, wait for the physical robot to move
                _, data = msg.split(" ", 1)
                uci_move, fen = data.split("|")
                print(f"Engines move: ({uci_move}) validated. Waiting for physical robot...")
                
                # Mutes microphone and waits for Arduino
                current_state = "ROBOT_MOVING"
                pub_state.send_string(current_state)

            elif msg.startswith("ROBOT_DONE"):
                # Serial node warns that physical movement is finished
                print("Robot finished physical movement. Back to player state")
                current_state = "PLAYER"
                pub_state.send_string(current_state)

            elif msg.startswith("GAME_OVER"):
                result = msg.split(" ", 1)[1]
                print(f"\nMate detected, result is: {result}")

            elif msg.startswith("BOARD_RESET"):
                print("Reseting board")
                current_state = "PLAYER"
                pub_state.send_string(current_state)

        except KeyboardInterrupt:
            print("\nmorte morte morte")
            break
        except Exception as e:
            print(f"Error in the state machine: {e}")
            time.sleep(0.1)

if __name__ == "__main__":
    main()