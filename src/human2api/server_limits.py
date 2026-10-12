"""Bound concurrent HTTP connections before allocating handler threads."""
from http.server import ThreadingHTTPServer
import threading


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, *args, **kwargs):
        self.connection_slots = threading.BoundedSemaphore(32)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        request.settimeout(15)
        if not self.connection_slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connection_slots.release()
