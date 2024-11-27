from datetime import datetime, timedelta
from typing import Dict

class SignalTracker:
    def __init__(self, expiry_minutes: int = 30):
        self.signals: Dict[str, datetime] = {}
        self.expiry_minutes = expiry_minutes
        
    def add_signal(self, symbol: str) -> None:
        """添加新信号"""
        self.signals[symbol] = datetime.now()
        
    def has_recent_signal(self, symbol: str) -> bool:
        """检查是否有最近的信号"""
        if symbol not in self.signals:
            return False
            
        signal_time = self.signals[symbol]
        expiry_time = signal_time + timedelta(minutes=self.expiry_minutes)
        
        if datetime.now() > expiry_time:
            del self.signals[symbol]
            return False
            
        return True
        
    def clear_expired_signals(self) -> None:
        """清理过期信号"""
        current_time = datetime.now()
        expired_symbols = [
            symbol for symbol, time in self.signals.items()
            if current_time > time + timedelta(minutes=self.expiry_minutes)
        ]
        
        for symbol in expired_symbols:
            del self.signals[symbol]