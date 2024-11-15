import time
import statistics
from typing import Dict, List
from datetime import datetime

class PerformanceTimer:
    """性能计时器类"""
    def __init__(self):
        self.start_time = None
        self.records: Dict[str, List[float]] = {}
        
    def start(self):
        """开始计时"""
        self.start_time = time.time()
        
    def stop(self, operation: str) -> float:
        """
        停止计时并记录
        返回耗时（秒）
        """
        if self.start_time is None:
            return 0
        
        duration = time.time() - self.start_time
        if operation not in self.records:
            self.records[operation] = []
        self.records[operation].append(duration)
        self.start_time = None
        return duration
    
    def get_statistics(self) -> dict:
        """获取统计信息"""
        stats = {}
        for operation, durations in self.records.items():
            stats[operation] = {
                'count': len(durations),
                'avg': statistics.mean(durations),
                'min': min(durations),
                'max': max(durations),
                'median': statistics.median(durations)
            }
        return stats