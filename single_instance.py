"""Route additional launches to the window using the same data directory."""
import hashlib
import json
import os
import time

from qt_compat import binding

if binding() == 'PySide2':
    from PySide2.QtCore import QLockFile
    from PySide2.QtNetwork import QLocalServer, QLocalSocket
else:
    from PySide6.QtCore import QLockFile
    from PySide6.QtNetwork import QLocalServer, QLocalSocket


class LaunchSession:
    def __init__(self, data):
        key = os.path.normcase(str(data.resolve()))
        self.name = 'wenju-' + hashlib.sha256(key.encode('utf-8')).hexdigest()[:32]
        self.lock = QLockFile(str(data / 'session.lock'))
        self.lock.setStaleLockTime(0)
        self.server = None
        self.handler = None
        self.pending = []
        self.clients = {}

    def acquire(self, files):
        payload = json.dumps(files, ensure_ascii=True).encode('ascii') + b'\n'
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.lock.tryLock(0):
                self.server = QLocalServer()
                self.server.setSocketOptions(QLocalServer.UserAccessOption)
                QLocalServer.removeServer(self.name)
                if not self.server.listen(self.name):
                    self.lock.unlock()
                    raise RuntimeError(self.server.errorString())
                self.server.newConnection.connect(self._accept)
                return True
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            if socket.waitForConnected(300):
                if socket.write(payload) == len(payload) and socket.waitForReadyRead(2000):
                    if bytes(socket.readAll()) == b'OK':
                        return False
                socket.abort()
                raise RuntimeError('Existing window did not acknowledge the launch')
            time.sleep(0.08)
        raise RuntimeError('Existing window is still starting or unresponsive')

    def set_handler(self, handler):
        self.handler = handler
        for files in self.pending:
            handler(files)
        self.pending.clear()

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.clients[socket] = bytearray()
            socket.disconnected.connect(lambda s=socket: self._discard(s))
            socket.readyRead.connect(lambda s=socket: self._read(s))
            self._read(socket)

    def _discard(self, socket):
        self.clients.pop(socket, None)
        socket.deleteLater()

    def _read(self, socket):
        data = self.clients[socket]
        data.extend(socket.readAll().data())
        if len(data) > 262144:
            socket.abort()
        elif data.endswith(b'\n'):
            try:
                files = json.loads(data)
                if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
                    raise ValueError('Invalid launch request')
            except ValueError:
                socket.abort()
                return
            if self.handler:
                self.handler(files)
            else:
                self.pending.append(files)
            socket.write(b'OK')
            socket.disconnectFromServer()

    def close(self):
        if self.server:
            self.server.close()
            self.lock.unlock()
