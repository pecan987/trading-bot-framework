"""
Simple file-based state store for testing without database requirements
"""
import os
import json
from datetime import datetime
from framework.execution.ccxt.state_persistence import StateStore


class SimpleStateStore(StateStore):
    """Simple file-based state store"""
    
    def __init__(self, exchange: str):
        self.exchange = exchange
        self.state_dir = "trading_state"
        os.makedirs(self.state_dir, exist_ok=True)
        
    def acquire_lock(self, lock_id: str) -> bool:
        """Simple lock - always allow for testing"""
        return True
        
    def release_lock(self, lock_id: str) -> bool:
        """Simple lock release"""
        return True
        
    def save_positions(self, positions) -> bool:
        """Save positions to JSON file"""
        try:
            filepath = os.path.join(self.state_dir, f"{self.exchange}_positions.json")
            with open(filepath, 'w') as f:
                json.dump(positions, f, indent=2)
            return True
        except Exception:
            return False
            
    def load_positions(self):
        """Load positions from JSON file"""
        try:
            filepath = os.path.join(self.state_dir, f"{self.exchange}_positions.json")
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    return json.load(f)
            return {}
        except Exception:
            return {}
            
    def save_orders(self, orders) -> bool:
        """Save orders to JSON file"""
        try:
            filepath = os.path.join(self.state_dir, f"{self.exchange}_orders.json")
            with open(filepath, 'w') as f:
                json.dump(orders, f, indent=2)
            return True
        except Exception:
            return False
            
    def load_orders(self):
        """Load orders from JSON file"""
        try:
            filepath = os.path.join(self.state_dir, f"{self.exchange}_orders.json")
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    return json.load(f)
            return {}
        except Exception:
            return {}
            
    def save_daily_pnl(self, date: str, pnl: float) -> bool:
        """Save daily P&L"""
        try:
            filepath = os.path.join(self.state_dir, f"{self.exchange}_pnl.json")
            pnl_data = {}
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    pnl_data = json.load(f)
            pnl_data[date] = pnl
            with open(filepath, 'w') as f:
                json.dump(pnl_data, f, indent=2)
            return True
        except Exception:
            return False
            
    def load_daily_pnl(self, date: str) -> float:
        """Load daily P&L"""
        try:
            filepath = os.path.join(self.state_dir, f"{self.exchange}_pnl.json")
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    pnl_data = json.load(f)
                return pnl_data.get(date, 0.0)
            return 0.0
        except Exception:
            return 0.0
            
    def save_checkpoint(self, data) -> bool:
        """Save checkpoint data"""
        try:
            filepath = os.path.join(self.state_dir, f"{self.exchange}_checkpoint.json")
            checkpoint = {
                'timestamp': datetime.now().isoformat(),
                'data': data
            }
            with open(filepath, 'w') as f:
                json.dump(checkpoint, f, indent=2)
            return True
        except Exception:
            return False
            
    def load_checkpoint(self):
        """Load checkpoint data"""
        try:
            filepath = os.path.join(self.state_dir, f"{self.exchange}_checkpoint.json")
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    checkpoint = json.load(f)
                return checkpoint.get('data', {})
            return {}
        except Exception:
            return {}