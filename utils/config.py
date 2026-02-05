import yaml
import os
from typing import Any, Dict, List, Optional, Tuple

class Config:
    """
    配置管理类，使用单例模式确保全局只有一个配置实例。
    负责加载、访问和更新应用的YAML配置文件。

    新架构支持slot-based配置：
    - 每个服务类型（chat/embedding/reranker/ocr）有2个槽位
    - 每个槽位可独立配置provider、base_url、api_key、model_name
    - 支持双模型对比、混排、降级等高级功能
    """
    _instance = None
    _config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.yaml')

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Config, cls).__new__(cls, *args, **kwargs)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        """加载YAML配置文件到实例的_data属性中"""
        try:
            with open(self._config_path, 'r', encoding='utf-8') as f:
                self._data = yaml.safe_load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"配置文件未找到: {self._config_path}")
        except Exception as e:
            raise IOError(f"读取或解析配置文件时出错: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        通过点分隔的键路径获取配置项。
        例如: get('llm_service.active_mode')
        """
        keys = key.split('.')
        value = self._data
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def get_all(self) -> Dict:
        """获取所有配置"""
        return self._data

    def set(self, key: str, value: Any):
        """
        通过点分隔的键路径设置配置项。
        例如: set('llm_service.active_mode', 'external')
        """
        keys = key.split('.')
        d = self._data
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value

    def save(self):
        """将当前配置保存回YAML文件"""
        try:
            with open(self._config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self._data, f, allow_unicode=True, sort_keys=False)
            # 重新加载配置以同步内存状态
            self._load_config()
        except Exception as e:
            raise IOError(f"保存配置文件时出错: {e}")

    def reload(self):
        """强制重新加载配置文件"""
        self._load_config()

    # ==================== 配置验证方法 ====================

    def validate_mode_configuration(self, mode: str) -> Tuple[bool, List[str]]:
        """
        验证指定模式的配置是否完整有效

        Args:
            mode: 服务模式 ('external', 'internal', 'local')

        Returns:
            (is_valid, warnings) - 是否有效和警告列表
        """
        is_valid = True
        warnings = []

        if mode == 'external':
            # 检查外部API服务配置
            # chat和embedding是必需的，reranker和ocr是可选的
            required_services = ['chat', 'embedding']
            optional_services = ['reranker', 'ocr']

            # 检查必需服务
            for service_type in required_services:
                configured_slots = self.get_configured_slots(service_type)
                if not configured_slots:
                    warnings.append(f"{self._get_service_type_display_name(service_type)}: 未配置任何槽位")
                    is_valid = False

            # 特别检查embedding（必须有激活的槽位）
            active_embedding_slot = self.get_active_embedding_slot()
            if not active_embedding_slot:
                warnings.append("向量化服务: 未设置激活的嵌入模型")
                is_valid = False

        elif mode == 'internal':
            # 检查内部服务配置（LLM和Embedding是必需的）
            internal_config = self.get_internal_config()
            if not internal_config.get('llm', {}).get('url'):
                warnings.append("内部服务: 未配置LLM服务地址")
                is_valid = False
            if not internal_config.get('embedding', {}).get('url'):
                warnings.append("内部服务: 未配置Embedding服务地址")
                is_valid = False
            # Reranker和OCR是可选的，不强制要求

        elif mode == 'local':
            # 检查本地Ollama配置
            local_config = self.get_local_config()
            if not local_config.get('host'):
                warnings.append("本地服务: 未配置Ollama服务地址")
                is_valid = False
            if not local_config.get('chat_model'):
                warnings.append("本地服务: 未配置聊天模型")
                is_valid = False
            if not local_config.get('embedding_model'):
                warnings.append("本地服务: 未配置嵌入模型")
                is_valid = False

        return is_valid, warnings

    def _get_service_type_display_name(self, service_type: str) -> str:
        """获取服务类型的显示名称"""
        names = {
            'chat': '聊天模型',
            'embedding': '向量化服务',
            'reranker': '重排序服务',
            'ocr': '文档解析服务'
        }
        return names.get(service_type, service_type)

    def get_mode_switch_warning(self, current_mode: str, new_mode: str) -> Optional[str]:
        """
        获取模式切换时的警告信息

        Args:
            current_mode: 当前模式
            new_mode: 目标模式

        Returns:
            警告信息，如果没有警告则返回None
        """
        warnings = []

        # 检查目标模式配置
        is_valid, validation_warnings = self.validate_mode_configuration(new_mode)
        warnings.extend(validation_warnings)

        # 检查知识库向量模型兼容性
        if current_mode == 'external' and new_mode != 'external':
            # 从外部模式切换到其他模式，需要提醒用户向量模型可能不兼容
            warnings.append("知识库向量模型: 切换到新模式后，现有知识库可能需要重新索引")

        if warnings:
            return "\n".join([f"⚠️ {w}" for w in warnings])
        return None

    @property
    def active_llm_mode(self) -> str:
        """获取当前激活的LLM服务模式"""
        return self.get('llm_service.active_mode', 'external')

    # ==================== Slot-based 配置访问方法 ====================

    def get_slot_config(self, service_type: str, slot_num: int) -> Dict:
        """
        获取指定服务类型和槽位的配置

        Args:
            service_type: 'chat', 'embedding', 'reranker', 'ocr'
            slot_num: 1 或 2

        Returns:
            槽位配置字典
        """
        slot_key = f'llm_service.external.{service_type}.slot_{slot_num}'
        return self.get(slot_key, {})

    def set_slot_config(self, service_type: str, slot_num: int, config: Dict):
        """
        设置指定服务类型和槽位的配置

        Args:
            service_type: 'chat', 'embedding', 'reranker', 'ocr'
            slot_num: 1 或 2
            config: 配置字典
        """
        slot_key = f'llm_service.external.{service_type}.slot_{slot_num}'
        for key, value in config.items():
            self.set(f'{slot_key}.{key}', value)

    def get_slot_field(self, service_type: str, slot_num: int, field: str, default: Any = None) -> Any:
        """
        获取槽位中的特定字段值

        Args:
            service_type: 'chat', 'embedding', 'reranker', 'ocr'
            slot_num: 1 或 2
            field: 字段名（如 'enabled', 'provider', 'api_key', 'model_name'等）
            default: 默认值

        Returns:
            字段值
        """
        return self.get(f'llm_service.external.{service_type}.slot_{slot_num}.{field}', default)

    def set_slot_field(self, service_type: str, slot_num: int, field: str, value: Any):
        """
        设置槽位中的特定字段值

        Args:
            service_type: 'chat', 'embedding', 'reranker', 'ocr'
            slot_num: 1 或 2
            field: 字段名
            value: 新值
        """
        self.set(f'llm_service.external.{service_type}.slot_{slot_num}.{field}', value)

    def is_slot_enabled(self, service_type: str, slot_num: int) -> bool:
        """
        检查槽位是否启用

        Args:
            service_type: 'chat', 'embedding', 'reranker', 'ocr'
            slot_num: 1 或 2

        Returns:
            是否启用
        """
        return self.get_slot_field(service_type, slot_num, 'enabled', False)

    def get_enabled_slots(self, service_type: str) -> List[int]:
        """
        获取指定服务类型所有启用的槽位列表

        Args:
            service_type: 'chat', 'embedding', 'reranker', 'ocr'

        Returns:
            启用的槽位编号列表，按优先级排序
        """
        enabled_slots = []
        for slot_num in [1, 2]:
            if self.is_slot_enabled(service_type, slot_num):
                enabled_slots.append(slot_num)
        # 按优先级排序
        enabled_slots.sort(key=lambda x: self.get_slot_field(service_type, x, 'priority', 999))
        return enabled_slots

    def get_active_embedding_slot(self) -> Optional[int]:
        """
        获取当前激活的嵌入模型槽位

        对于embedding服务类型，只能有一个槽位处于激活状态

        Returns:
            激活的槽位编号，如果没有激活的则返回None
        """
        for slot_num in [1, 2]:
            if self.get_slot_field('embedding', slot_num, 'active', False):
                return slot_num
        return None

    def set_active_embedding_slot(self, slot_num: int):
        """
        设置激活的嵌入模型槽位

        会自动将其他槽位的active标志设为False

        Args:
            slot_num: 1 或 2
        """
        for s in [1, 2]:
            self.set_slot_field('embedding', s, 'active', (s == slot_num))

    # ==================== 槽位配置验证 ====================

    def is_slot_configured(self, service_type: str, slot_num: int) -> bool:
        """
        检查槽位是否有有效配置

        有效配置需要：
        - 已启用
        - 有provider（或custom_provider_name）
        - 有api_key且不是占位符

        Args:
            service_type: 'chat', 'embedding', 'reranker', 'ocr'
            slot_num: 1 或 2

        Returns:
            是否有有效配置
        """
        if not self.is_slot_enabled(service_type, slot_num):
            return False

        provider = self.get_slot_field(service_type, slot_num, 'provider', '')
        api_key = self.get_slot_field(service_type, slot_num, 'api_key', '')

        # 检查provider是否有效
        if provider == 'other':
            custom_name = self.get_slot_field(service_type, slot_num, 'custom_provider_name', '')
            if not custom_name:
                return False
        elif not provider:
            return False

        # 检查api_key是否有效（不是占位符）
        if not api_key or api_key.startswith('sk-your-') or api_key == 'your-':
            return False

        return True

    def get_configured_slots(self, service_type: str) -> List[int]:
        """
        获取已有效配置的槽位列表

        Args:
            service_type: 'chat', 'embedding', 'reranker', 'ocr'

        Returns:
            已配置的槽位编号列表，按优先级排序
        """
        configured = []
        for slot_num in [1, 2]:
            if self.is_slot_configured(service_type, slot_num):
                configured.append(slot_num)
        configured.sort(key=lambda x: self.get_slot_field(service_type, x, 'priority', 999))
        return configured

    # ==================== 提供商预设配置 ====================

    def get_provider_presets(self) -> Dict:
        """获取所有提供商预设配置"""
        return self.get('provider_presets', {})

    def get_provider_preset(self, provider: str, service_type: str) -> Dict:
        """
        获取指定提供商和服务类型的预设配置

        Args:
            provider: 提供商名称（如 'qwen', 'deepseek' 等）
            service_type: 'chat', 'embedding', 'reranker', 'ocr'

        Returns:
            预设配置字典
        """
        return self.get(f'provider_presets.{provider}.{service_type}', {})

    def get_available_providers(self, service_type: str) -> List[str]:
        """
        获取支持指定服务类型的所有提供商列表

        Args:
            service_type: 'chat', 'embedding', 'reranker', 'ocr'

        Returns:
            提供商名称列表
        """
        providers = []
        presets = self.get_provider_presets()
        for provider_name, provider_config in presets.items():
            if service_type in provider_config and provider_config[service_type]:
                providers.append(provider_name)
        return providers

    def get_provider_models(self, provider: str, service_type: str) -> Dict:
        """
        获取指定提供商和服务类型的模型列表

        Args:
            provider: 提供商名称
            service_type: 'chat', 'embedding', 'reranker', 'ocr'

        Returns:
            模型配置字典
        """
        return self.get(f'provider_presets.{provider}.{service_type}.models', {})

    def get_provider_base_urls(self, provider: str, service_type: str) -> List[str]:
        """
        获取指定提供商和服务类型的推荐Base URL列表

        Args:
            provider: 提供商名称
            service_type: 'chat', 'embedding', 'reranker', 'ocr'

        Returns:
            Base URL列表
        """
        return self.get(f'provider_presets.{provider}.{service_type}.base_urls', [])

    # ==================== 内部和本地服务配置 ====================

    def get_internal_config(self) -> Dict:
        """获取内网服务配置"""
        return self.get('llm_service.internal', {})

    def get_local_config(self) -> Dict:
        """获取本地Ollama配置"""
        return self.get('llm_service.local', {})

    # ==================== 向下兼容方法（保持向后兼容） ====================

    def get_llm_config(self) -> Dict:
        """
        获取当前激活模式下的LLM配置（兼容旧代码）

        Returns:
            配置字典
        """
        mode = self.active_llm_mode

        if mode == 'external':
            return {
                'mode': 'external',
                'chat': self._get_service_config_external('chat'),
                'embedding': self._get_service_config_external('embedding'),
                'reranker': self._get_service_config_external('reranker'),
                'ocr': self._get_service_config_external('ocr')
            }
        elif mode == 'internal':
            config = self.get_internal_config()
            if not config:
                raise ValueError("未找到内部服务配置")
            return {'mode': 'internal', **config}
        elif mode == 'local':
            config = self.get_local_config()
            if not config:
                raise ValueError("未找到本地服务配置")
            return {'mode': 'local', **config}
        else:
            raise ValueError(f"未知的服务模式: '{mode}'")

    def _get_service_config_external(self, service_type: str) -> Dict:
        """
        获取外部服务配置（兼容旧格式）

        将新的slot配置转换为旧的多提供商格式
        """
        enabled_slots = self.get_enabled_slots(service_type)
        result = {}

        for slot_num in enabled_slots:
            slot_config = self.get_slot_config(service_type, slot_num)
            provider = slot_config.get('provider', 'unknown')

            # 为兼容旧代码，将slot配置转换为provider配置
            result[provider] = {
                'api_key': slot_config.get('api_key', ''),
                'base_url': slot_config.get('base_url', ''),
                'models': {
                    slot_config.get('model_name', ''): {
                        'display_name': slot_config.get('display_name', ''),
                        'enabled': True
                    }
                },
                'slot_num': slot_num,  # 记录槽位编号
                'priority': slot_config.get('priority', 999),
                'active': slot_config.get('active', False)  # 仅用于embedding
            }

        # 设置active_provider为优先级最高的
        if enabled_slots:
            result['active_provider'] = self.get_slot_config(service_type, enabled_slots[0]).get('provider', '')

        return result

    # ==================== 废弃方法警告（保持兼容性） ====================

    def get_active_provider(self, service_type: str) -> str:
        """
        [已废弃] 获取指定服务类型的激活提供商
        请使用 get_slot_config() 方法
        """
        enabled_slots = self.get_enabled_slots(service_type)
        if enabled_slots:
            return self.get_slot_field(service_type, enabled_slots[0], 'provider', 'qwen')
        return 'qwen'

    def get_service_providers(self, service_type: str) -> Dict:
        """
        [已废弃] 获取指定服务类型的所有提供商配置
        请使用 get_slot_config() 和 get_enabled_slots() 方法
        """
        return self._get_service_config_external(service_type)

    def get_provider_config(self, service_type: str, provider: str) -> Dict:
        """
        [已废弃] 获取指定服务类型和提供商的配置
        请使用 get_slot_config() 方法
        """
        # 查找对应provider的slot
        for slot_num in [1, 2]:
            if self.get_slot_field(service_type, slot_num, 'provider', '') == provider:
                return self.get_slot_config(service_type, slot_num)
        return {}

    def get_model_config(self, service_type: str, provider: str, model_name: str) -> Dict:
        """
        [已废弃] 获取指定模型的具体配置
        请使用 get_slot_config() 方法
        """
        slot_config = self.get_provider_config(service_type, provider)
        if slot_config and slot_config.get('model_name') == model_name:
            return {
                'display_name': slot_config.get('display_name', ''),
                'enabled': True
            }
        return {}

    def get_selected_model(self, capability: str) -> Dict[str, str]:
        """
        [已废弃] 获取指定能力的选中模型
        请使用 get_slot_config() 方法
        """
        enabled_slots = self.get_enabled_slots(capability)
        if enabled_slots:
            slot_config = self.get_slot_config(capability, enabled_slots[0])
            return {
                'provider': slot_config.get('provider', ''),
                'model': slot_config.get('model_name', ''),
                'slot': enabled_slots[0]
            }
        return {}

    def set_selected_model(self, capability: str, provider: str, model: str):
        """
        [已废弃] 设置指定能力的选中模型
        请使用 set_slot_config() 方法
        """
        # 查找对应provider的slot并设置模型
        for slot_num in [1, 2]:
            if self.get_slot_field(capability, slot_num, 'provider', '') == provider:
                self.set_slot_field(capability, slot_num, 'model_name', model)
                break


# 创建一个全局配置实例，供应用各模块导入和使用
config = Config()
