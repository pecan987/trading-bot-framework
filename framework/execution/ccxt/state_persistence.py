"""
Abstract state persistence interface for easy switching between backends
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime


class StateStore(ABC):
    """Abstract interface for state persistence"""
    
    @abstractmethod
    def save_positions(self, positions: Dict[str, Any]) -> bool:
        """Save positions to storage"""
        pass
        
    @abstractmethod
    def load_positions(self) -> Dict[str, Any]:
        """Load positions from storage"""
        pass
        
    @abstractmethod
    def save_orders(self, orders: Dict[str, Any]) -> bool:
        """Save orders to storage"""
        pass
        
    @abstractmethod
    def load_orders(self) -> Dict[str, Any]:
        """Load orders from storage"""
        pass
        
    @abstractmethod
    def save_daily_pnl(self, date: str, pnl: float) -> bool:
        """Save daily P&L"""
        pass
        
    @abstractmethod
    def load_daily_pnl(self, date: str) -> float:
        """Load daily P&L for given date"""
        pass
        
    @abstractmethod
    def acquire_lock(self, lock_id: str) -> bool:
        """Acquire a lock to prevent multiple instances"""
        pass
        
    @abstractmethod
    def release_lock(self, lock_id: str) -> bool:
        """Release the lock"""
        pass
        
    @abstractmethod
    def save_checkpoint(self, data: Dict[str, Any]) -> bool:
        """Save full checkpoint of state"""
        pass
        
    @abstractmethod
    def load_checkpoint(self) -> Optional[Dict[str, Any]]:
        """Load latest checkpoint"""
        pass