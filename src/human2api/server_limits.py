"""Bound concurrent HTTP connections before allocating handler threads."""
from http.server import ThreadingHTTPServer
import threading
from email.message import Message


def unique_security_headers(headers: Message) -> bool:
    """Reject ambiguous identity/origin headers before selecting any value."""
    if len(headers.get_all("Host", [])) != 1:
        return False
    return all(len(headers.get_all(name, [])) <= 1 for name in
               ("Origin", "Authorization", "X-H2A-Token", "Content-Type"))


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

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
