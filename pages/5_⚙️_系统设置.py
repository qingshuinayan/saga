# 📜 saga/pages/4_⚙️_系统设置.py

import streamlit as st
import os
from utils.config import config
from utils.database import db_manager
from utils.logging_config import logger

st.set_page_config(page_title="系统设置", page_icon="⚙️", layout="wide")
st.title("⚙️ 系统设置")
st.markdown("配置应用的各项参数和服务。**更改将实时保存到 `config.yaml` 文件中。**")

# ==================== LLM 服务模式选择 ====================
st.subheader("🤖 LLM 服务模式")

mode_descriptions = {
    'external': '🌐 **外部API服务**（推荐）- 按服务类型配置多个提供商',
    'internal': '🏢 **企业内网服务** - 仅限企业网络环境使用',
    'local': '💻 **本地Ollama服务** - 需要在本地运行Ollama'
}

current_mode = config.get('llm_service.active_mode', 'external')

col1, col2 = st.columns([3, 1])

with col1:
    selected_mode = st.radio(
        "选择服务模式:",
        options=['external', 'internal', 'local'],
        format_func=lambda x: mode_descriptions.get(x, x).split('**')[1].split('**')[0] if '**' in mode_descriptions.get(x, x) else x,
        index=['external', 'internal', 'local'].index(current_mode) if current_mode in ['external', 'internal', 'local'] else 0,
        horizontal=False,
        label_visibility="collapsed"
    )

with col2:
    if st.button("🔄 应用模式", use_container_width=True):
        if selected_mode != current_mode:
            # 验证目标模式配置
            is_valid, warnings = config.validate_mode_configuration(selected_mode)
            mode_switch_warning = config.get_mode_switch_warning(current_mode, selected_mode)

            if not is_valid:
                st.error(f"无法切换到 {selected_mode} 模式，配置不完整：")
                for warning in warnings:
                    st.warning(f"⚠️ {warning}")
            elif mode_switch_warning:
                # 有警告但可以切换
                st.warning(f"切换模式注意事项：\n{mode_switch_warning}")
                config.set('llm_service.active_mode', selected_mode)
                config.save()
                st.success(f"LLM服务模式已切换为: {selected_mode}")
                st.info("模式切换后，建议重启应用以确保所有服务完全重新加载。")
                st.rerun()
            else:
                # 直接切换，没有警告
                config.set('llm_service.active_mode', selected_mode)
                config.save()
                st.success(f"LLM服务模式已切换为: {selected_mode}")
                st.info("模式切换后，建议重启应用以确保所有服务完全重新加载。")
                st.rerun()

st.info(mode_descriptions.get(selected_mode, selected_mode))

st.divider()

# ==================== 提供商信息 ====================
PROVIDER_INFO = {
    'qwen': {'name': '阿里通义千问', 'icon': '🔵'},
    'deepseek': {'name': 'DeepSeek', 'icon': '🟢'},
    'openai': {'name': 'OpenAI (GPT)', 'icon': '🔴'},
    'anthropic': {'name': 'Anthropic (Claude)', 'icon': '🟠'},
    'google': {'name': 'Google (Gemini)', 'icon': '🟡'},
    'glm': {'name': '智谱AI (GLM)', 'icon': '🟣'},
    'other': {'name': '其他/自定义', 'icon': '⚪'}
}

# ==================== 外部API服务配置（Slot-based） ====================
if selected_mode == 'external':
    st.subheader("🌐 外部API服务配置")

    # 定义4个服务类型的Tab
    tab_names = ["🗨️ 聊天模型", "🔤 向量化", "🎯 重排序", "📄 文档解析"]
    service_types = ['chat', 'embedding', 'reranker', 'ocr']
    service_descriptions = [
        "两个槽位可同时激活，用于左右分栏对比",
        "两个槽位只能有一个激活（向量库隔离要求）",
        "两个槽位可同时激活，用于混排重排序",
        "两个槽位按优先级降级（slot_1失败则尝试slot_2）"
    ]

    tabs = st.tabs(tab_names)

    for tab_idx, (tab, service_type, description) in enumerate(zip(tabs, service_types, service_descriptions)):
        with tab:
            st.markdown(f"#### {tab_names[tab_idx]} - 双槽位配置")
            st.caption(description)
            st.markdown("---")

            # 获取该服务类型的可用提供商列表
            available_providers = config.get_available_providers(service_type)

            # ==================== Slot 1 配置 ====================
            with st.expander("🎯 **槽位 1 (主槽位)**", expanded=True):
                slot_1_config = config.get_slot_config(service_type, 1)

                col_enable, col_provider = st.columns([1, 3])

                with col_enable:
                    slot_1_enabled = st.checkbox(
                        "启用",
                        value=slot_1_config.get('enabled', False),
                        key=f"{service_type}_slot_1_enabled"
                    )

                with col_provider:
                    # 提供商选择
                    provider_names = available_providers

                    current_provider = slot_1_config.get('provider', 'qwen')
                    if current_provider in provider_names:
                        default_idx = provider_names.index(current_provider)
                    else:
                        default_idx = 0

                    slot_1_provider = st.selectbox(
                        "提供商",
                        options=provider_names,
                        format_func=lambda x: f"{PROVIDER_INFO.get(x, {}).get('icon', '🔹')} {PROVIDER_INFO.get(x, {}).get('name', x)}",
                        index=default_idx,
                        key=f"{service_type}_slot_1_provider"
                    )

                # 如果选择了"other"，显示自定义提供商名称输入框
                if slot_1_provider == 'other':
                    slot_1_custom_name = st.text_input(
                        "自定义提供商名称",
                        value=slot_1_config.get('custom_provider_name', ''),
                        key=f"{service_type}_slot_1_custom_name",
                        help="输入自定义提供商的名称"
                    )
                else:
                    slot_1_custom_name = ''

                # Base URL（显示预设URL，也允许自定义）
                preset_urls = config.get_provider_base_urls(slot_1_provider, service_type)
                if preset_urls:
                    default_url = preset_urls[0]
                    if slot_1_config.get('base_url', ''):
                        default_url = slot_1_config.get('base_url', '')
                else:
                    default_url = slot_1_config.get('base_url', '')

                slot_1_base_url = st.text_input(
                    "Base URL",
                    value=default_url,
                    key=f"{service_type}_slot_1_base_url",
                    help="API服务的基础URL"
                )

                # API Key
                slot_1_api_key = st.text_input(
                    "API Key",
                    value=slot_1_config.get('api_key', ''),
                    type="password",
                    key=f"{service_type}_slot_1_api_key",
                    help=f"在 {PROVIDER_INFO.get(slot_1_provider, {}).get('name', '')} 获取"
                )

                # 模型名称 - 简化为单个输入框
                slot_1_model = st.text_input(
                    "模型名称",
                    value=slot_1_config.get('model_name', ''),
                    key=f"{service_type}_slot_1_model",
                    help="实际调用API时使用的模型名称，例如: gpt-4o, qwen-plus, text-embedding-v3 等"
                )

                # === 服务类型特定配置 ===

                # Embedding: Active标志
                if service_type == 'embedding':
                    slot_1_active = st.checkbox(
                        "✅ 设为当前激活的嵌入模型",
                        value=slot_1_config.get('active', False),
                        key=f"{service_type}_slot_1_active",
                        help="知识库将使用此模型进行向量化（只能有一个激活）"
                    )
                else:
                    slot_1_active = slot_1_config.get('active', False)

                # Reranker: Weight配置
                if service_type == 'reranker':
                    slot_1_weight = st.slider(
                        "混排权重",
                        0.0, 1.0, slot_1_config.get('weight', 0.6), 0.1,
                        key=f"{service_type}_slot_1_weight",
                        help="混排时此槽位的权重，两个槽位权重之和应为1.0"
                    )
                else:
                    slot_1_weight = slot_1_config.get('weight', 0.6)

                # Embedding: Dimension配置
                if service_type == 'embedding':
                    slot_1_dimension = st.number_input(
                        "向量维度",
                        value=slot_1_config.get('dimension', 1536),
                        min_value=128,
                        max_value=10000,
                        step=128,
                        key=f"{service_type}_slot_1_dimension"
                    )
                else:
                    slot_1_dimension = slot_1_config.get('dimension', 1536)

                # Batch Size配置（仅Embedding需要）
                if service_type == 'embedding':
                    slot_1_batch_size = st.number_input(
                        "批处理大小",
                        value=slot_1_config.get('batch_size', 10),
                        min_value=1,
                        max_value=100,
                        key=f"{service_type}_slot_1_batch_size"
                    )
                else:
                    slot_1_batch_size = slot_1_config.get('batch_size', 10)

                # Priority（默认1）
                slot_1_priority = 1

                # 保存按钮
                if st.button("💾 保存槽位1配置", key=f"{service_type}_slot_1_save", use_container_width=True):
                    # 构建配置
                    new_config = {
                        'enabled': slot_1_enabled,
                        'priority': slot_1_priority,
                        'provider': slot_1_provider,
                        'custom_provider_name': slot_1_custom_name,
                        'base_url': slot_1_base_url,
                        'api_key': slot_1_api_key,
                        'model_name': slot_1_model,
                        'display_name': slot_1_model  # 简化：直接使用模型名称作为显示名称
                    }

                    # 添加服务类型特定字段
                    if service_type == 'embedding':
                        new_config['active'] = slot_1_active
                        new_config['dimension'] = slot_1_dimension
                        new_config['batch_size'] = slot_1_batch_size
                    elif service_type == 'reranker':
                        new_config['weight'] = slot_1_weight
                    # OCR 不需要额外的配置字段

                    config.set_slot_config(service_type, 1, new_config)

                    # 如果是embedding且设置为active，需要清除其他slot的active标志
                    if service_type == 'embedding' and slot_1_active:
                        config.set_active_embedding_slot(1)

                    config.save()
                    st.success("✅ 槽位1配置已保存")
                    st.rerun()

            st.markdown("---")

            # ==================== Slot 2 配置 ====================
            with st.expander("🎯 **槽位 2 (副槽位)**", expanded=False):
                slot_2_config = config.get_slot_config(service_type, 2)

                col_enable, col_provider = st.columns([1, 3])

                with col_enable:
                    slot_2_enabled = st.checkbox(
                        "启用",
                        value=slot_2_config.get('enabled', False),
                        key=f"{service_type}_slot_2_enabled"
                    )

                with col_provider:
                    current_provider = slot_2_config.get('provider', 'deepseek')
                    if current_provider in provider_names:
                        default_idx = provider_names.index(current_provider)
                    else:
                        default_idx = 0 if len(provider_names) > 1 else 0

                    slot_2_provider = st.selectbox(
                        "提供商",
                        options=provider_names,
                        format_func=lambda x: f"{PROVIDER_INFO.get(x, {}).get('icon', '🔹')} {PROVIDER_INFO.get(x, {}).get('name', x)}",
                        index=default_idx,
                        key=f"{service_type}_slot_2_provider"
                    )

                # 如果选择了"other"，显示自定义提供商名称输入框
                if slot_2_provider == 'other':
                    slot_2_custom_name = st.text_input(
                        "自定义提供商名称",
                        value=slot_2_config.get('custom_provider_name', ''),
                        key=f"{service_type}_slot_2_custom_name",
                        help="输入自定义提供商的名称"
                    )
                else:
                    slot_2_custom_name = ''

                # Base URL
                preset_urls = config.get_provider_base_urls(slot_2_provider, service_type)
                if preset_urls:
                    default_url = preset_urls[0]
                    if slot_2_config.get('base_url', ''):
                        default_url = slot_2_config.get('base_url', '')
                else:
                    default_url = slot_2_config.get('base_url', '')

                slot_2_base_url = st.text_input(
                    "Base URL",
                    value=default_url,
                    key=f"{service_type}_slot_2_base_url",
                    help="API服务的基础URL"
                )

                # API Key
                slot_2_api_key = st.text_input(
                    "API Key",
                    value=slot_2_config.get('api_key', ''),
                    type="password",
                    key=f"{service_type}_slot_2_api_key",
                    help=f"在 {PROVIDER_INFO.get(slot_2_provider, {}).get('name', '')} 获取"
                )

                # 模型名称 - 简化为单个输入框
                slot_2_model = st.text_input(
                    "模型名称",
                    value=slot_2_config.get('model_name', ''),
                    key=f"{service_type}_slot_2_model",
                    help="实际调用API时使用的模型名称，例如: gpt-4o, qwen-plus, text-embedding-v3 等"
                )

                # === 服务类型特定配置 ===

                # Embedding: Active标志
                if service_type == 'embedding':
                    slot_2_active = st.checkbox(
                        "✅ 设为当前激活的嵌入模型",
                        value=slot_2_config.get('active', False),
                        key=f"{service_type}_slot_2_active",
                        help="知识库将使用此模型进行向量化（只能有一个激活）"
                    )
                else:
                    slot_2_active = slot_2_config.get('active', False)

                # Reranker: Weight配置
                if service_type == 'reranker':
                    slot_2_weight = st.slider(
                        "混排权重",
                        0.0, 1.0, slot_2_config.get('weight', 0.4), 0.1,
                        key=f"{service_type}_slot_2_weight",
                        help="混排时此槽位的权重，两个槽位权重之和应为1.0"
                    )
                else:
                    slot_2_weight = slot_2_config.get('weight', 0.4)

                # Embedding: Dimension配置
                if service_type == 'embedding':
                    slot_2_dimension = st.number_input(
                        "向量维度",
                        value=slot_2_config.get('dimension', 1536),
                        min_value=128,
                        max_value=10000,
                        step=128,
                        key=f"{service_type}_slot_2_dimension"
                    )
                else:
                    slot_2_dimension = slot_2_config.get('dimension', 1536)

                # Batch Size配置（仅Embedding需要）
                if service_type == 'embedding':
                    slot_2_batch_size = st.number_input(
                        "批处理大小",
                        value=slot_2_config.get('batch_size', 10),
                        min_value=1,
                        max_value=100,
                        key=f"{service_type}_slot_2_batch_size"
                    )
                else:
                    slot_2_batch_size = slot_2_config.get('batch_size', 10)

                # Priority（默认2）
                slot_2_priority = 2

                # 保存按钮
                if st.button("💾 保存槽位2配置", key=f"{service_type}_slot_2_save", use_container_width=True):
                    # 构建配置
                    new_config = {
                        'enabled': slot_2_enabled,
                        'priority': slot_2_priority,
                        'provider': slot_2_provider,
                        'custom_provider_name': slot_2_custom_name,
                        'base_url': slot_2_base_url,
                        'api_key': slot_2_api_key,
                        'model_name': slot_2_model,
                        'display_name': slot_2_model  # 简化：直接使用模型名称作为显示名称
                    }

                    # 添加服务类型特定字段
                    if service_type == 'embedding':
                        new_config['active'] = slot_2_active
                        new_config['dimension'] = slot_2_dimension
                        new_config['batch_size'] = slot_2_batch_size
                    elif service_type == 'reranker':
                        new_config['weight'] = slot_2_weight
                    # OCR 不需要额外的配置字段

                    config.set_slot_config(service_type, 2, new_config)

                    # 如果是embedding且设置为active，需要清除其他slot的active标志
                    if service_type == 'embedding' and slot_2_active:
                        config.set_active_embedding_slot(2)

                    config.save()
                    st.success("✅ 槽位2配置已保存")
                    st.rerun()

            # ==================== 当前状态显示 ====================
            st.markdown("---")
            st.markdown("#### 📌 当前配置状态")

            enabled_slots = config.get_enabled_slots(service_type)
            if enabled_slots:
                for slot_num in enabled_slots:
                    slot_config = config.get_slot_config(service_type, slot_num)
                    provider = slot_config.get('provider', '')
                    model = slot_config.get('model_name', '')

                    status_text = f"🎯 **槽位 {slot_num}**: {PROVIDER_INFO.get(provider, {}).get('icon', '🔹')} {PROVIDER_INFO.get(provider, {}).get('name', provider)} / {model}"

                    if service_type == 'embedding':
                        if slot_config.get('active', False):
                            status_text += " ✅ **[当前激活]**"
                        else:
                            status_text += " ⏸️ [未激活]"

                    st.info(status_text)
            else:
                st.warning("⚠️ 当前没有启用的槽位，请至少启用并配置一个槽位")

# ==================== 企业内网服务配置 ====================
elif selected_mode == 'internal':
    st.subheader("🏢 企业内网服务配置")
    st.info("内部服务配置通常由IT部门统一管理，此处为只读显示。")
    internal_config = config.get_internal_config()
    if internal_config:
        st.json(internal_config)
    else:
        st.warning("未找到内部服务配置")

# ==================== 本地Ollama服务配置 ====================
elif selected_mode == 'local':
    st.subheader("💻 本地Ollama服务配置")
    local_config = config.get_local_config()

    with st.form("local_ollama_form"):
        enabled = st.checkbox(
            "启用本地Ollama服务",
            value=local_config.get('enabled', False),
            help="确保Ollama已在本地运行"
        )

        host = st.text_input(
            "Ollama服务地址",
            value=local_config.get('host', 'http://localhost:11434'),
            help="默认为 http://localhost:11434"
        )

        col1, col2 = st.columns(2)
        with col1:
            chat_model = st.text_input(
                "聊天模型",
                value=local_config.get('chat_model', 'qwen:7b'),
                help="例如: qwen:7b, llama2:13b, qwen3:0.6b"
            )
        with col2:
            embedding_model = st.text_input(
                "Embedding模型",
                value=local_config.get('embedding_model', 'mxbai-embed-large'),
                help="例如: mxbai-embed-large, nomic-embed-text, qwen3-embedding:0.6b"
            )

        col3, col4 = st.columns(2)
        with col3:
            reranker_model = st.text_input(
                "Reranker模型 (可选)",
                value=local_config.get('reranker_model', ''),
                help="例如: bge-reranker-base, dengcao/Qwen3-Reranker-0.6B:Q8_0"
            )
        with col4:
            ocr_model = st.text_input(
                "OCR模型",
                value=local_config.get('ocr_model', 'qwen3-vl:2b'),
                help="多模态视觉模型，例如: qwen3-vl:2b, llava:latest"
            )

        if st.form_submit_button("💾 保存本地Ollama配置"):
            config.set('llm_service.local.enabled', enabled)
            config.set('llm_service.local.host', host)
            config.set('llm_service.local.chat_model', chat_model)
            config.set('llm_service.local.embedding_model', embedding_model)
            config.set('llm_service.local.reranker_model', reranker_model)
            config.set('llm_service.local.ocr_model', ocr_model)
            config.save()
            st.success("本地Ollama配置已保存")

st.divider()

# ==================== 其他核心配置 ====================
col_kb, col_conv, col_rag = st.columns(3)

with col_kb:
    with st.expander("📚 知识库设置", expanded=True):
        with st.form("kb_settings_form"):
            chunk_size = st.number_input(
                "文本块大小 (字符)",
                min_value=100,
                max_value=5000,
                value=config.get('knowledge_base.chunk_size', 1000),
                help="每个文本块的最大字符数"
            )
            chunk_overlap = st.number_input(
                "文本块重叠 (字符)",
                min_value=0,
                max_value=500,
                value=config.get('knowledge_base.chunk_overlap', 150),
                help="相邻文本块之间的重叠字符数"
            )
            top_k = st.number_input(
                "初步检索数量 (Top-K)",
                min_value=1,
                max_value=20,
                value=config.get('knowledge_base.top_k', 10),
                help="从向量库中检索出的候选文档数量"
            )
            rerank_top_n = st.number_input(
                "精排后数量 (Top-N)",
                min_value=1,
                max_value=10,
                value=config.get('knowledge_base.rerank_top_n', 3),
                help="经过Reranker重排序后，最终提供给LLM的文档数量"
            )

            st.markdown("---")
            st.markdown("**高级检索功能**")
            enable_hyde = st.toggle(
                "启用 HyDE (假设性文档嵌入)",
                value=config.get('knowledge_base.enable_hyde', False),
                help="对于模糊查询，让AI先生成一个假想答案再进行搜索"
            )
            enable_agentic_rag = st.toggle(
                "启用 Agentic RAG (查询分析与重写)",
                value=config.get('knowledge_base.enable_agentic_rag', True),
                help="让AI分析用户问题，决定是否需要检索"
            )
            relevance_threshold = st.slider(
                "向量距离阈值",
                0.0,
                2.0,
                config.get('knowledge_base.relevance_threshold', 1.2),
                0.1,
                help="ChromaDB L2 距离阈值，值越小要求越严"
            )

            if st.form_submit_button("💾 保存知识库配置"):
                config.set('knowledge_base.chunk_size', int(chunk_size))
                config.set('knowledge_base.chunk_overlap', int(chunk_overlap))
                config.set('knowledge_base.top_k', int(top_k))
                config.set('knowledge_base.rerank_top_n', int(rerank_top_n))
                config.set('knowledge_base.enable_hyde', enable_hyde)
                config.set('knowledge_base.enable_agentic_rag', enable_agentic_rag)
                config.set('knowledge_base.relevance_threshold', relevance_threshold)
                config.save()
                st.success("知识库配置已保存")

with col_conv:
    with st.expander("💬 对话设置", expanded=True):
        with st.form("conv_settings_form"):
            temperature = st.slider(
                "温度 (Temperature)",
                0.0,
                2.0,
                config.get('conversation.default_temperature', 0.3),
                0.1,
                help="控制输出的随机性，越低越确定"
            )
            top_p = st.slider(
                "Top-p",
                0.0,
                1.0,
                config.get('conversation.default_top_p', 0.9),
                0.05,
                help="核采样参数，控制输出的多样性"
            )
            context_token_budget = st.number_input(
                "上下文Token预算",
                min_value=1000,
                max_value=32000,
                value=config.get('conversation.context_token_budget', 6000),
                step=1000,
                help="历史对话部分占用的最大Token数量"
            )

            if st.form_submit_button("💾 保存对话配置"):
                config.set('conversation.default_temperature', float(temperature))
                config.set('conversation.default_top_p', float(top_p))
                config.set('conversation.context_token_budget', int(context_token_budget))
                config.save()
                st.success("对话配置已保存")

with col_rag:
    with st.expander("📄 RAG文档解析设置", expanded=True):
        st.markdown("**解析策略说明**:")
        st.caption("• 企业内网模式：优先使用MinerU解析PDF（支持公式、表格）")
        st.caption("• 外部API/本地模式：使用配置的OCR服务解析文档")

        with st.form("rag_parsing_form"):
            parsing_timeout = st.number_input(
                "解析超时时间 (秒)",
                min_value=60,
                max_value=3600,
                value=config.get('rag_parsing.parsing_timeout', 600),
                step=60,
                help="文档解析的最大等待时间"
            )

            if st.form_submit_button("💾 保存RAG解析配置"):
                config.set('rag_parsing.parsing_timeout', int(parsing_timeout))
                config.save()
                st.success("RAG解析配置已保存")

st.divider()

# ==================== 系统状态与快速操作 ====================
st.subheader("📊 系统状态")

col_stat, col_op = st.columns(2)

with col_stat:
    st.markdown("**当前状态**")

    # 获取当前模式
    current_mode = config.get('llm_service.active_mode', 'external')

    # 根据模式显示不同的状态信息
    if current_mode == 'external':
        # 外部API模式：显示槽位状态
        def get_slot_status(service_type):
            enabled_slots = config.get_enabled_slots(service_type)
            if not enabled_slots:
                return "未配置"

            status_list = []
            for slot_num in enabled_slots:
                slot_config = config.get_slot_config(service_type, slot_num)
                provider = slot_config.get('provider', '')
                model = slot_config.get('model_name', '')
                status_list.append(f"{PROVIDER_INFO.get(provider, {}).get('icon', '🔹')} {model}")

            return " + ".join(status_list)

        st.info(f"""
        - **服务模式**: 🌐 外部API
        - **聊天模型**: `{get_slot_status('chat')}`
        - **向量模型**: `{get_slot_status('embedding')}`
        - **重排模型**: `{get_slot_status('reranker')}`
        - **文档解析**: `{get_slot_status('ocr')}`
        """)

    elif current_mode == 'internal':
        # 企业内网模式：显示内部服务状态
        internal_config = config.get_internal_config()
        st.info(f"""
        - **服务模式**: 🏢 企业内网
        - **LLM模型**: `{internal_config.get('llm', {}).get('model', '未配置')}`
        - **向量模型**: `{internal_config.get('embedding', {}).get('model', '未配置')}`
        - **重排模型**: `{internal_config.get('reranker', {}).get('model', '未配置')}`
        - **MinerU**: `{'启用' if internal_config.get('mineru', {}).get('enabled') else '禁用'}`
        """)

    else:  # local
        # 本地Ollama模式：显示本地服务状态
        local_config = config.get_local_config()
        st.info(f"""
        - **服务模式**: 💻 本地Ollama
        - **服务地址**: `{local_config.get('host', '未配置')}`
        - **聊天模型**: `{local_config.get('chat_model', '未配置')}`
        - **向量模型**: `{local_config.get('embedding_model', '未配置')}`
        - **重排模型**: `{local_config.get('reranker_model', '未配置') or '未配置'}`
        """)

    # 通用信息（所有模式都显示）
    st.info(f"""
    - **知识库总数**: `{len(db_manager.list_knowledge_bases())}`
    - **对话主题数**: `{len(db_manager.list_topics())}`
    """)

with col_op:
    st.markdown("**快速操作**")

    if st.button("🧹 清理临时文件", use_container_width=True):
        import shutil
        temp_dir = os.path.join(config.get('paths.data'), 'uploads', 'temp')
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            os.makedirs(temp_dir, exist_ok=True)
            st.success("临时文件已清理！")
        else:
            st.info("没有临时文件需要清理")

    log_file = os.path.join(config.get('paths.logs'), 'saga_app.log')
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8') as f:
            st.download_button(
                label="📋 下载最新日志",
                data=f.read(),
                file_name="saga_app.log",
                mime="text/plain",
                use_container_width=True
            )

st.divider()
st.caption("Saga 个人知识助手 - 支持多领域、多模型的专家知识助手")
