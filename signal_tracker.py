from datetime import datetime, timedelta


class SignalTracker:
    def __init__(self, expiry_minutes=30):
        self.signals = {}  # 存储信号的字典
        self.expiry_minutes = expiry_minutes
    
    def add_signal(self, symbol: str):
        """添加新的信号"""
        self.signals[symbol] = datetime.now()
        
    def has_recent_signal(self, symbol: str) -> bool:
        """检查是否存在有效期内的信号"""
        if symbol not in self.signals:
            return False
            
        signal_time = self.signals[symbol]
        current_time = datetime.now()
        
        # 如果信号在有效期内
        if current_time - signal_time < timedelta(minutes=self.expiry_minutes):
            return True
            
        # 如果信号已过期，删除它
        del self.signals[symbol]
        return False
        
    def clean_expired_signals(self):
        """清理过期的信号"""
        current_time = datetime.now()
        expired_symbols = [
            symbol for symbol, signal_time in self.signals.items()
            if current_time - signal_time >= timedelta(minutes=self.expiry_minutes)
        ]
        
        for symbol in expired_symbols:
            del self.signals[symbol]
