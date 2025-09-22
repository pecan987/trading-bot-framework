"""
Prometheus metrics server for trading bot
Exposes latency and trading metrics via HTTP endpoint
"""
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class MetricsHandler(BaseHTTPRequestHandler):
    """HTTP handler for Prometheus metrics endpoint"""
    
    def do_GET(self):
        """Handle GET requests for metrics"""
        if self.path == '/metrics':
            try:
                # Import here to avoid dependency issues
                from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
                
                metrics_data = generate_latest()
                
                self.send_response(200)
                self.send_header('Content-Type', CONTENT_TYPE_LATEST)
                self.send_header('Content-Length', str(len(metrics_data)))
                self.end_headers()
                self.wfile.write(metrics_data)
                
            except ImportError:
                # Prometheus client not available
                self.send_response(503)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Prometheus client not available')
                
            except Exception as e:
                logger.error(f"Error serving metrics: {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(f'Error: {str(e)}'.encode())
                
        elif self.path == '/health':
            # Health check endpoint
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
            
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')
    
    def log_message(self, format, *args):
        """Override to use our logger"""
        logger.debug(f"HTTP {format % args}")


class MetricsServer:
    """Prometheus metrics HTTP server"""
    
    def __init__(self, port: int = 8000, host: str = '0.0.0.0'):
        self.port = port
        self.host = host
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        
    def start(self):
        """Start the metrics server in a background thread"""
        if self.running:
            logger.warning("Metrics server is already running")
            return
            
        try:
            self.server = HTTPServer((self.host, self.port), MetricsHandler)
            self.thread = threading.Thread(target=self._run_server, daemon=True)
            self.thread.start()
            self.running = True
            
            logger.info(f"Metrics server started on http://{self.host}:{self.port}/metrics")
            
        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}")
            
    def _run_server(self):
        """Run the HTTP server"""
        try:
            self.server.serve_forever()
        except Exception as e:
            logger.error(f"Metrics server error: {e}")
        finally:
            self.running = False
            
    def stop(self):
        """Stop the metrics server"""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            
        if self.thread:
            self.thread.join(timeout=5)
            
        self.running = False
        logger.info("Metrics server stopped")


# Global metrics server instance
_metrics_server: Optional[MetricsServer] = None


def start_metrics_server(port: int = 8000, host: str = '0.0.0.0') -> bool:
    """Start the global metrics server"""
    global _metrics_server
    
    if _metrics_server and _metrics_server.running:
        logger.info("Metrics server already running")
        return True
        
    try:
        _metrics_server = MetricsServer(port, host)
        _metrics_server.start()
        return _metrics_server.running
        
    except Exception as e:
        logger.error(f"Failed to start metrics server: {e}")
        return False


def stop_metrics_server():
    """Stop the global metrics server"""
    global _metrics_server
    
    if _metrics_server:
        _metrics_server.stop()
        _metrics_server = None


def get_metrics_server() -> Optional[MetricsServer]:
    """Get the global metrics server instance"""
    return _metrics_server