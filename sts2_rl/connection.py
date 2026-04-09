"""TCP server for communicating with the STS2 RL Bridge mod."""

import json
import socket
import logging

logger = logging.getLogger(__name__)


class ConnectionServer:
    """TCP server that accepts a connection from the STS2 game mod.

    Protocol: newline-delimited JSON over TCP.
    The game connects as client; Python is the server.
    """

    def __init__(self, port: int = 19720, host: str = "127.0.0.1", timeout: float = 120.0):
        self.port = port
        self.host = host
        self.timeout = timeout
        self._server_socket: socket.socket | None = None
        self._client_socket: socket.socket | None = None
        self._buffer = ""

    def start(self) -> None:
        """Bind and listen for a game connection."""
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen(1)
        self._server_socket.settimeout(self.timeout)
        logger.info(f"Listening on {self.host}:{self.port}")

    def wait_for_connection(self) -> None:
        """Block until the game connects."""
        if self._server_socket is None:
            raise RuntimeError("Server not started")
        logger.info("Waiting for game to connect...")
        self._client_socket, addr = self._server_socket.accept()
        self._client_socket.settimeout(self.timeout)
        logger.info(f"Game connected from {addr}")

    def receive(self) -> dict:
        """Receive a single JSON message from the game."""
        if self._client_socket is None:
            raise RuntimeError("No client connected")

        while "\n" not in self._buffer:
            data = self._client_socket.recv(65536)
            if not data:
                raise ConnectionError("Game disconnected")
            self._buffer += data.decode("utf-8")

        line, self._buffer = self._buffer.split("\n", 1)
        msg = json.loads(line)
        logger.debug(f"Received: {msg.get('type', '?')} / {msg.get('decision_type', '?')}")
        return msg

    def send(self, msg: dict) -> None:
        """Send a JSON message to the game."""
        if self._client_socket is None:
            raise RuntimeError("No client connected")

        line = json.dumps(msg, separators=(",", ":")) + "\n"
        self._client_socket.sendall(line.encode("utf-8"))
        logger.debug(f"Sent: {msg.get('type', '?')} / {msg.get('action_type', '?')}")

    def close(self) -> None:
        """Close all sockets."""
        if self._client_socket:
            self._client_socket.close()
            self._client_socket = None
        if self._server_socket:
            self._server_socket.close()
            self._server_socket = None
        self._buffer = ""

    def reset_connection(self) -> None:
        """Close the client connection and wait for a new one."""
        if self._client_socket:
            self._client_socket.close()
            self._client_socket = None
        self._buffer = ""
        self.wait_for_connection()
