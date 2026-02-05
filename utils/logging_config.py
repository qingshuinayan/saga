import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from .config import config

def setup_logging():
    """
    配置并返回一个全局 logger，支持按天轮转日志文件。
    """
    log_level_str = config.get('app.log_level', 'INFO').upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    log_dir = config.get('paths.logs', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # 基础日志文件名
    log_file = os.path.join(log_dir, 'saga_app.log')

    # 创建 logger
    logger = logging.getLogger('SagaLogger')
    logger.setLevel(log_level)

    # 防止重复添加 handlers
    if logger.hasHandlers():
        logger.handlers.clear()

    # 创建格式化器
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(module)s.%(funcName)s:%(lineno)d - %(message)s'
    )

    # --- 控制台 Handler ---
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    # --- 文件 Handler (TimedRotating，按天) ---
    # 每天凌晨滚动日志，保留最近30天的日志
    file_handler = TimedRotatingFileHandler(
        log_file,
        when='midnight',  # 每天凌晨
        interval=1,       # 间隔1天
        backupCount=30,   # 保留30天
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.suffix = "%Y-%m-%d.log"  # 日志文件后缀格式
    logger.addHandler(file_handler)

    return logger

# 创建一个全局 logger 实例
logger = setup_logging()