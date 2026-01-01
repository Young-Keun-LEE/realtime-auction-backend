from fastapi import WebSocket
from typing import List

class ConnectionManager:
    def __init__(self):
        # Manage all currently connected WebSockets in a list (in memory)
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"📡 New Client Connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        print(f"🔌 Client Disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        # Send a message to all connected clients (Fan-out)
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                # Handle disconnected sockets
                pass

# Create an instance to be used globally
manager = ConnectionManager()