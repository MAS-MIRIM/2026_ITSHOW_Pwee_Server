import eventlet
eventlet.monkey_patch()

import eventlet.wsgi
eventlet.wsgi.MAX_REQUEST_LINE = 65536

from app import create_app
from app.api.multi_socket import socketio

app = create_app()

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001, debug=True)
