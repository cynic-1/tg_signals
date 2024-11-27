import logging
from pathlib import Path
from datetime import datetime

def setup_logger(name: str = None) -> logging.Logger:
    """
    设置日志配置
    
    Args:
        name: logger名称
        
    Returns:
        logging.Logger: 配置好的logger实例
    """
    # 创建logs目录
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # 创建logger
    logger = logging.getLogger(name or __name__)
    logger.setLevel(logging.DEBUG)
    
    # 如果logger已经有handlers，直接返回
    if logger.handlers:
        return logger
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    
    # 创建文件处理器
    current_time = datetime.now().strftime("%Y%m%d")
    file_handler = logging.FileHandler(
        log_dir / f"crypto_bot_{current_time}.log",
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    
    # 添加处理器
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger

# 创建默认logger实例
logger = setup_logger('crypto_bot')