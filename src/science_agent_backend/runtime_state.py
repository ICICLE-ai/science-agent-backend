"""Active requests shared by conversation, upload, and WebSocket routes."""
active_sessions: set[str] = set()
