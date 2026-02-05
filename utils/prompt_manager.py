# 📜 saga/utils/prompt_manager.py
import os
from jinja2 import Environment, FileSystemLoader, Template
from typing import Optional, Dict, Any
from .logging_config import logger

class PromptManager:
    """
    提示词管理类，支持两种来源的提示词：
    1. 文件系统中的Jinja2模板（原有功能）
    2. 数据库中存储的可编辑提示词（新增功能）
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(PromptManager, cls).__new__(cls, *args, **kwargs)
            prompt_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts')
            if not os.path.isdir(prompt_dir):
                raise FileNotFoundError(f"Prompt templates directory not found: {prompt_dir}")
            cls._instance.env = Environment(loader=FileSystemLoader(prompt_dir), trim_blocks=True, lstrip_blocks=True)
            cls._instance._editable_template = None  # 缓存可编辑提示词模板
            logger.info(f"PromptManager initialized. Loading templates from: {prompt_dir}")
        return cls._instance

    def render(self, template_name: str, **kwargs) -> str:
        """渲染指定的Jinja2模板（文件系统）"""
        try:
            template = self.env.get_template(template_name)
            return template.render(**kwargs)
        except Exception as e:
            error_msg = f"Error rendering prompt template '{template_name}': {e}"
            logger.error(error_msg, exc_info=True)
            return f"PROMPT_RENDERING_ERROR: {error_msg}"

    def render_db_prompt(self, prompt_data: Dict[str, Any], context: str = None) -> str:
        """
        渲染数据库中存储的可编辑提示词

        Args:
            prompt_data: 包含提示词各部分的字典
            context: 可选的知识库上下文

        Returns:
            渲染后的完整提示词字符串
        """
        try:
            # 获取或加载可编辑提示词模板
            if self._editable_template is None:
                self._editable_template = self.env.get_template('editable_prompt.jinja2')

            # 准备模板变量
            template_vars = {
                'role_definition': prompt_data.get('role_definition', ''),
                'profile': prompt_data.get('profile'),
                'skills': prompt_data.get('skills'),
                'rules': prompt_data.get('rules'),
                'workflows': prompt_data.get('workflows'),
                'output_format': prompt_data.get('output_format'),
                'display_name': prompt_data.get('display_name', ''),
                'context': context
            }

            return self._editable_template.render(**template_vars)

        except Exception as e:
            error_msg = f"Error rendering database prompt: {e}"
            logger.error(error_msg, exc_info=True)
            return f"PROMPT_RENDERING_ERROR: {error_msg}"

    def get_system_prompt(self, prompt_type: str, context: str = None, use_db: bool = True) -> str:
        """
        获取系统提示词，优先使用数据库中的激活提示词

        Args:
            prompt_type: 提示词类型 ('system', 'chitchat')
            context: 可选的知识库上下文
            use_db: 是否使用数据库中的提示词

        Returns:
            完整的提示词字符串
        """
        # 延迟导入以避免循环依赖
        from .database import db_manager

        # 确保默认提示词已初始化
        db_manager.init_default_prompts()

        if use_db:
            # 尝试从数据库获取激活的提示词
            prompt_data = db_manager.get_active_prompt_by_type(prompt_type)
            if prompt_data:
                logger.debug(f"Using database prompt for type: {prompt_type}")
                return self.render_db_prompt(prompt_data, context)

        # 降级到文件系统模板
        template_name = f"{prompt_type}_prompt.jinja2"
        logger.debug(f"Using file template: {template_name}")
        return self.render(template_name, context=context or "")

# 创建一个全局实例
prompt_manager = PromptManager()
