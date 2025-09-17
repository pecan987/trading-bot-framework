import time
import asyncio
from datetime import datetime
from functools import wraps
from typing import Dict, Any, Optional, Callable
from decimal import Decimal
import threading
from collections import defaultdict, deque

from framework.utils.logger import get_logger

logger = get_logger(__name__)


class LatencyMetrics:
    """Thread-safe latency metrics collector."""
    
    def __init__(self, max_samples: int = 1000):
        self.max_samples = max_samples
        self._lock = threading.Lock()
        self._metrics = defaultdict(lambda: {
            'samples': deque(maxlen=max_samples),
            'total_calls': 0,
            'total_time': 0.0,
            'min_latency': float('inf'),
            'max_latency': 0.0,
            'errors': 0
        })
        
    def record(self, endpoint: str, latency: float, error: bool = False):
        """Record latency measurement."""
        with self._lock:
            metrics = self._metrics[endpoint]
            metrics['samples'].append(latency)
            metrics['total_calls'] += 1
            metrics['total_time'] += latency
            
            if not error:
                metrics['min_latency'] = min(metrics['min_latency'], latency)
                metrics['max_latency'] = max(metrics['max_latency'], latency)
            else:
                metrics['errors'] += 1
                
    def get_stats(self, endpoint: str) -> Dict[str, Any]:
        """Get statistics for an endpoint."""
        with self._lock:
            if endpoint not in self._metrics:
                return {}
                
            metrics = self._metrics[endpoint]
            samples = list(metrics['samples'])
            
            if not samples:
                return {}
                
            # Calculate percentiles
            sorted_samples = sorted(samples)
            n = len(sorted_samples)
            
            stats = {
                'endpoint': endpoint,
                'total_calls': metrics['total_calls'],
                'total_time': metrics['total_time'],
                'avg_latency': metrics['total_time'] / max(metrics['total_calls'], 1),
                'min_latency': metrics['min_latency'] if metrics['min_latency'] != float('inf') else 0,
                'max_latency': metrics['max_latency'],
                'errors': metrics['errors'],
                'error_rate': metrics['errors'] / max(metrics['total_calls'], 1),
                'sample_count': n
            }
            
            # Add percentiles
            if n > 0:
                stats['p50'] = sorted_samples[int(n * 0.5)]
                stats['p90'] = sorted_samples[int(n * 0.9)]
                stats['p95'] = sorted_samples[int(n * 0.95)]
                stats['p99'] = sorted_samples[int(n * 0.99)]
                
            return stats
            
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all endpoints."""
        with self._lock:
            return {endpoint: self.get_stats(endpoint) for endpoint in self._metrics.keys()}
            
    def reset(self):
        """Reset all metrics."""
        with self._lock:
            self._metrics.clear()


# Global latency collector
latency_collector = LatencyMetrics()


def measure_latency(endpoint: str, log_slow_requests: bool = True, slow_threshold: float = 1.0):
    """Decorator to measure API latency."""
    def decorator(func):
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            error = False
            
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                error = True
                raise
            finally:
                latency = time.time() - start_time
                latency_collector.record(endpoint, latency, error)
                
                # Log slow requests
                if log_slow_requests and latency > slow_threshold:
                    logger.warning(f"Slow API call: {endpoint} took {latency:.3f}s")
                    
                # Log all requests at debug level
                logger.debug(f"API call: {endpoint} took {latency:.3f}s (error: {error})")
                
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            error = False
            
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                error = True
                raise
            finally:
                latency = time.time() - start_time
                latency_collector.record(endpoint, latency, error)
                
                # Log slow requests
                if log_slow_requests and latency > slow_threshold:
                    logger.warning(f"Slow API call: {endpoint} took {latency:.3f}s")
                    
                # Log all requests at debug level
                logger.debug(f"API call: {endpoint} took {latency:.3f}s (error: {error})")
                
        # Return appropriate wrapper based on whether function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
            
    return decorator


def get_latency_stats(endpoint: Optional[str] = None) -> Dict[str, Any]:
    """Get latency statistics."""
    if endpoint:
        return latency_collector.get_stats(endpoint)
    else:
        return latency_collector.get_all_stats()


def reset_latency_stats():
    """Reset latency statistics."""
    latency_collector.reset()


# Context manager for measuring code blocks
class LatencyTimer:
    """Context manager to measure latency of code blocks."""
    
    def __init__(self, endpoint: str, log_slow_requests: bool = True, slow_threshold: float = 1.0):
        self.endpoint = endpoint
        self.log_slow_requests = log_slow_requests
        self.slow_threshold = slow_threshold
        self.start_time = None
        
    def __enter__(self):
        self.start_time = time.time()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        latency = time.time() - self.start_time
        error = exc_type is not None
        
        latency_collector.record(self.endpoint, latency, error)
        
        # Log slow requests
        if self.log_slow_requests and latency > self.slow_threshold:
            logger.warning(f"Slow operation: {self.endpoint} took {latency:.3f}s")
            
        # Log all operations at debug level
        logger.debug(f"Operation: {self.endpoint} took {latency:.3f}s (error: {error})")


# Prometheus metrics integration
try:
    from prometheus_client import Histogram, Counter, Gauge
    
    # Define Prometheus metrics
    api_latency_histogram = Histogram(
        'api_latency_seconds',
        'API request latency in seconds',
        ['endpoint', 'method'],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
    )
    
    api_requests_total = Counter(
        'api_requests_total',
        'Total API requests',
        ['endpoint', 'method', 'status']
    )
    
    api_latency_current = Gauge(
        'api_latency_current_seconds',
        'Current API latency in seconds',
        ['endpoint', 'method']
    )
    
    def record_prometheus_metrics(endpoint: str, latency: float, error: bool = False, method: str = 'unknown'):
        """Record metrics to Prometheus."""
        try:
            api_latency_histogram.labels(endpoint=endpoint, method=method).observe(latency)
            api_latency_current.labels(endpoint=endpoint, method=method).set(latency)
            
            status = 'error' if error else 'success'
            api_requests_total.labels(endpoint=endpoint, method=method, status=status).inc()
            
        except Exception as e:
            logger.error(f"Failed to record Prometheus metrics: {e}")
            
    # Enhanced decorator with Prometheus support
    def measure_api_latency(endpoint: str, method: str = 'unknown', 
                           log_slow_requests: bool = True, slow_threshold: float = 1.0,
                           prometheus_enabled: bool = True):
        """Enhanced decorator with Prometheus support."""
        def decorator(func):
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.time()
                error = False
                
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    error = True
                    raise
                finally:
                    latency = time.time() - start_time
                    
                    # Record in local collector
                    latency_collector.record(endpoint, latency, error)
                    
                    # Record in Prometheus
                    if prometheus_enabled:
                        record_prometheus_metrics(endpoint, latency, error, method)
                    
                    # Log slow requests
                    if log_slow_requests and latency > slow_threshold:
                        logger.warning(f"Slow API call: {endpoint} took {latency:.3f}s")
                        
                    # Log all requests at debug level
                    logger.debug(f"API call: {endpoint} took {latency:.3f}s (error: {error})")
                    
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.time()
                error = False
                
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    error = True
                    raise
                finally:
                    latency = time.time() - start_time
                    
                    # Record in local collector
                    latency_collector.record(endpoint, latency, error)
                    
                    # Record in Prometheus
                    if prometheus_enabled:
                        record_prometheus_metrics(endpoint, latency, error, method)
                    
                    # Log slow requests
                    if log_slow_requests and latency > slow_threshold:
                        logger.warning(f"Slow API call: {endpoint} took {latency:.3f}s")
                        
                    # Log all requests at debug level
                    logger.debug(f"API call: {endpoint} took {latency:.3f}s (error: {error})")
                    
            # Return appropriate wrapper based on whether function is async
            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            else:
                return sync_wrapper
                
        return decorator
        
except ImportError:
    logger.warning("Prometheus client not available. Metrics will not be exported.")
    
    def measure_api_latency(endpoint: str, method: str = 'unknown', 
                           log_slow_requests: bool = True, slow_threshold: float = 1.0,
                           prometheus_enabled: bool = False):
        """Fallback decorator without Prometheus support."""
        return measure_latency(endpoint, log_slow_requests, slow_threshold)