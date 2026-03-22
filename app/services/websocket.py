from fastapi import WebSocket
from typing import List

class ConnectionManager:
    def __init__(self):
        # Manage all currently connected WebSockets in a list (in memory)
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, auction_id: str):
        await websocket.accept()
        # If there is no list for this auction_id, create one
        if auction_id not in self.active_connections:
            self.active_connections[auction_id] = []
        # Put the new connection in the list for this auction_id
        self.active_connections[auction_id].append(websocket)
        print(f"📡 New Client Connected. auction_id: {auction_id}")

    def disconnect(self, websocket: WebSocket, auction_id: str):
        if auction_id in self.active_connections:
            self.active_connections[auction_id].remove(websocket)
            if not self.active_connections[auction_id]:  # If no more connections for this auction_id, remove the key
                del self.active_connections[auction_id]
        print(f"🔌 Client Disconnected. auction_id: {auction_id}")

    async def broadcast_to_auction(self, message: str, auction_id: str):
        # Send a message to specific auction_id clients
        if auction_id in self.active_connections:
            for connection in self.active_connections[auction_id]:
                await connection.send_text(message)
            print(f"📣 [Broadcasting] New Price: {message} to auction_id: {auction_id}")

# Create an instance to be used globally
manager = ConnectionManager()