# 📜 saga/pages/1_💬_智能对话.py

import streamlit as st
import time
import os
import re
import json
from typing import List, Dict
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.exceptions import OutputParserException

# --- 导入自定义模块 ---
from utils.database import db_manager
from utils.knowledge_base import kb_manager
from utils.llm_service import llm_service, count_tokens
from utils.logging_config import logger
from utils.config import config
from utils.prompt_manager import prompt_manager
from utils.pydantic_models import QueryAnalysisResult

# -------------------
# 1. 页面基础设置
# -------------------
st.set_page_config(page_title="智能对话", page_icon="💬", layout="wide")
st.title("💬 智能对话")
st.markdown("与您的AI专家智囊进行深入交流")

# -------------------
# 2. 初始化会话状态
# -------------------
if "current_topic_id" not in st.session_state:
    st.session_state.current_topic_id = None
if "selected_kbs" not in st.session_state:
    st.session_state.selected_kbs = []
if "file_context_for_next_prompt" not in st.session_state:
    st.session_state.file_context_for_next_prompt = None
if "confirming_delete" not in st.session_state:
    st.session_state.confirming_delete = None
if "token_stats" not in st.session_state:
    st.session_state.token_stats = {} # 用于存储和显示Token消耗
if "kb_selection_initialized" not in st.session_state:
    st.session_state.kb_selection_initialized = False
    
# 用于防止文件重复处理的旗标
if "processed_file_id" not in st.session_state:
    st.session_state.processed_file_id = None
    
# 使用新的变量来存储临时文件上下文
if "temp_file_text" not in st.session_state:
    st.session_state.temp_file_text = None
    
if "last_response_sources" not in st.session_state:
    st.session_state.last_response_sources = []

# -------------------
# 3. 辅助函数
# -------------------
def cut_thinking_txt(text: str) -> str:
    """使用正则表达式移除</think>前的内容，专门用于处理模型的思考过程。"""
    if not text: return ""
    pattern = r'(.*?)<\/think>'
    result = re.sub(pattern, '', text, flags=re.DOTALL)
    result = re.sub(r'\n+', '\n', result).strip()
    return result

def auto_generate_title(topic_id, user_prompt, assistant_response):
    """在首轮对话后，调用LLM为新话题生成一个简洁的标题。"""
    
    title_generation_prompt = prompt_manager.render(
        'title_generation.jinja2', 
        user_prompt=user_prompt, 
        assistant_response=assistant_response
    )

    try:
        messages_for_title = [
            # {"role": "system", "content": "You are an assistant that generates short, concise titles based on a conversation."},
            {"role": "user", "content": title_generation_prompt}
        ]
        # 使用轻量调用，不需要上下文管理
        raw_response = llm_service._lightweight_chat_completion(
            messages_for_title, 
            # topic_id=topic_id, # topic_id 仍需传递以避免错误
            temperature=0.1
        )
        clean_response = cut_thinking_txt(raw_response)
        if clean_response:
            # 智能提取最后一行有效文本，增强鲁棒性
            lines = [line.strip() for line in clean_response.strip().split('\n') if line.strip()]
            new_title = lines[-1] if lines else clean_response
            # 进一步清理
            new_title = re.sub(r'^[标题：\s"\']+|[\s"\']+$', '', new_title)
            # new_title = new_title[:8] # 强制截断
            if new_title:
                db_manager.update_topic_title(topic_id, new_title)
                logger.info(f"为 Topic ID {topic_id} 自动生成标题: '{new_title}'")
                return True
    except Exception as e:
        logger.error(f"自动生成标题失败: {e}", exc_info=True)
    return False

def render_citations(response_text: str, source_documents: List[Dict]):
    """解析AI回答中的引用标签，并在文末统一展示可展开的溯源信息。"""
    # 替换主文本中的标签，使其更简洁
    formatted_response = re.sub(r'\[(来源-\d+)\]', r' `\1`', response_text)
    st.markdown(formatted_response, unsafe_allow_html=True)

    # 提取所有引用ID
    citation_ids = sorted(list(set(re.findall(r'\[(来源-\d+)\]', response_text))))
    
    if citation_ids:
        st.markdown("---")
        # 构建从 citation_id 到文档内容的映射
        citation_map = {doc.get('citation_id'): doc for doc in source_documents if doc.get('citation_id')}
        
        for cid in citation_ids:
            if cid in citation_map:
                source_doc = citation_map[cid]
                with st.expander(f"**{cid}**: {source_doc.get('metadata', {}).get('source', '未知来源')}"):
                    st.markdown(source_doc.get('content', '内容为空'))

# -------------------
# 4. 侧边栏 (Sidebar)
# -------------------
with st.sidebar:
    st.header("对话管理")
    if st.button("➕ 新建对话", use_container_width=True):
        new_title = f"新对话 - {time.strftime('%Y-%m-%d %H:%M')}"
        topic_id = db_manager.add_topic(new_title)
        st.session_state.current_topic_id = topic_id
        st.session_state.file_context_for_next_prompt = None
        st.session_state.confirming_delete = None
        st.session_state.token_stats = {} # 重置token统计
        st.session_state.kb_selection_initialized = False # 重置知识库选择初始化标志
        logger.info(f"创建新主题: ID={topic_id}, Title='{new_title}'")
        st.rerun()

    st.divider()

    st.subheader("历史对话")
    topics = db_manager.list_topics()
    
    if not st.session_state.current_topic_id and topics:
        st.session_state.current_topic_id = topics[0]['id']

    # --- 删除确认逻辑 ---
    if st.session_state.confirming_delete:
        topic_to_delete = db_manager.get_topic_by_id(st.session_state.confirming_delete)
        if topic_to_delete:
            with st.expander(f"⚠️ 确认删除 '{topic_to_delete['title']}'?", expanded=True):
                st.warning("此操作将永久删除该话题及其所有对话记录，无法恢复。")
                col1, col2 = st.columns(2)
                if col1.button("确认", use_container_width=True, type="primary"):
                    # 删除ChromaDB中的相关集合（如果需要）
                    # kb_manager.delete_collections_for_topic(...) # 这是一个可以扩展的功能
                    db_manager.delete_topic(st.session_state.confirming_delete)
                    st.session_state.confirming_delete = None
                    st.session_state.current_topic_id = None
                    st.rerun()
                if col2.button("取消", use_container_width=True):
                    st.session_state.confirming_delete = None
                    st.rerun()

    # --- 标题修改与历史列表 ---
    for topic in topics:
        is_selected = (topic['id'] == st.session_state.current_topic_id)

        col1, col2 = st.columns([0.94, 0.06])
        with col1:
            button_type = "primary" if is_selected else "secondary"
            display_title = f"▶ {topic['title']}" if is_selected else topic['title']
            if st.button(display_title, use_container_width=True, type=button_type, key=f"topic_btn_{topic['id']}", disabled=is_selected):
                st.session_state.current_topic_id = topic['id']
                # 清除所有临时上下文
                st.session_state.file_context_for_next_prompt = None
                st.session_state.temp_file_text = None
                st.session_state.processed_file_id = None
                st.session_state.last_response_sources = []
                st.session_state.confirming_delete = None
                st.session_state.token_stats = {} # 切换对话时重置
                st.session_state.kb_selection_initialized = False # 重置知识库选择初始化标志
                st.rerun()
        with col2:
            if st.button("🗑️", key=f"del_btn_{topic['id']}", help=f"删除话题 '{topic['title']}'"):
                st.session_state.confirming_delete = topic['id']
                st.rerun()

    st.divider()

    st.subheader("知识库选择")

    # 获取当前激活的向量模型
    active_embedding_model = llm_service.get_active_embedding_model_name()

    # 获取所有知识库，并过滤出与当前模式兼容的
    all_kbs = db_manager.list_knowledge_bases()
    compatible_kbs = [kb for kb in all_kbs if kb.get("embedding_model") == active_embedding_model]

    # 初始化知识库选择（只在切换对话或新建对话时执行一次）
    if not st.session_state.kb_selection_initialized and st.session_state.current_topic_id:
        # 获取该对话之前使用的知识库
        saved_kb_ids = db_manager.get_topic_knowledge_bases(st.session_state.current_topic_id)

        if saved_kb_ids:
            # 恢复之前的知识库选择（只保留仍然存在且兼容的）
            saved_kb_names = [kb["name"] for kb in compatible_kbs if kb["id"] in saved_kb_ids]
            st.session_state.selected_kbs = saved_kb_names
        else:
            # 新建对话：清空知识库选择
            st.session_state.selected_kbs = []

        st.session_state.kb_selection_initialized = True
    else:
        # 如果已经初始化过，过滤掉不兼容的知识库选择
        if st.session_state.selected_kbs:
            valid_kbs = [kb for kb in all_kbs if kb["name"] in st.session_state.selected_kbs and kb.get("embedding_model") == active_embedding_model]
            st.session_state.selected_kbs = [kb["name"] for kb in valid_kbs]

    # 显示知识库选择器（只显示兼容的知识库）
    kb_names = [kb["name"] for kb in compatible_kbs]

    if kb_names:
        new_selected_kbs = st.multiselect(
            "选择要加载的知识库 (可多选):",
            options=kb_names,
            default=st.session_state.selected_kbs if st.session_state.selected_kbs else [],
            key="kb_selector"
        )

        # 检查知识库选择是否发生变化
        if set(new_selected_kbs) != set(st.session_state.selected_kbs):
            st.session_state.selected_kbs = new_selected_kbs

            # 保存到数据库
            if st.session_state.current_topic_id:
                new_kb_ids = [kb["id"] for kb in compatible_kbs if kb["name"] in new_selected_kbs]
                db_manager.update_topic_knowledge_bases(st.session_state.current_topic_id, new_kb_ids)

            st.rerun()
    else:
        st.caption("当前服务模式下没有可用的知识库")
    
    st.divider()
    
    # Token 消耗统计
    st.subheader("Token 统计")
    stats = st.session_state.get("token_stats", {})
    if stats:
        st.info(f"""
        **上次交互消耗:**
        - **请求:** {stats.get('request_tokens', 0)} Tokens
        - **响应:** {stats.get('response_tokens', 0)} Tokens
        - **总计:** {stats.get('total_tokens', 0)} Tokens
        """)
    else:
        st.caption("暂无Token消耗记录。")


# -------------------
# 5. 主聊天界面
# -------------------
if not st.session_state.current_topic_id:
    st.info("欢迎使用Saga，请点击左侧“新建对话”或选择一个历史对话来开始。")
else:
    # --- 临时文件上传器 ---
    uploaded_file = st.file_uploader(
        "在此上传临时文件进行分析 (txt, md, pdf, png, jpg):", 
        type=['txt', 'md', 'pdf', 'png', 'jpg', 'jpeg'], 
        key=f"file_uploader_{st.session_state.current_topic_id}"
    )
    if uploaded_file:
        if uploaded_file.file_id != st.session_state.get('processed_file_id'):
            with st.spinner(f"正在处理上传的文件 '{uploaded_file.name}'..."):
                file_content = ""
                # 使用 llm_service 的 ocr 功能统一处理
                # 先保存临时文件
                temp_dir = os.path.join(config.get('paths.uploads'), "temp")
                os.makedirs(temp_dir, exist_ok=True)
                temp_file_path = os.path.join(temp_dir, uploaded_file.name)
                with open(temp_file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

                # 调用 llm_service 的统一接口
                extraction_result = llm_service.extract_text_from_file(temp_file_path)
                
                if extraction_result and extraction_result.get('text'):
                    file_content = extraction_result.get('text')
                    
                    st.session_state.temp_file_text = file_content
                    st.session_state.processed_file_id = uploaded_file.file_id # 记录已处理文件的ID
                    st.success(f"文件 '{uploaded_file.name}' 已处理完毕。请在下方输入框中就此文件提问。")
                else:
                    st.error(f"无法从文件 '{uploaded_file.name}' 中提取内容。")
                
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)

    # --- 聊天记录显示：每次渲染都从数据库重新加载，确保数据最新 ---
    messages = db_manager.get_messages_by_topic(st.session_state.current_topic_id)
    
    for i, message in enumerate(messages):
        with st.chat_message(message["role"]):
            # 只对最后一条 assistant 消息尝试渲染溯源
            if message["role"] == "assistant" and i == len(messages) - 1 and st.session_state.last_response_sources:
                render_citations(message["content"], st.session_state.last_response_sources)
            else:
                st.markdown(message["content"], unsafe_allow_html=True)

    # --- 粘性聊天输入框 st.chat_input 会始终固定在浏览器窗口底部---
    if prompt := st.chat_input("请在此输入您的问题... (Shift+Enter 换行)"):
        
        # 保存并显示用户消息
        db_manager.add_message(st.session_state.current_topic_id, "user", prompt)
        st.session_state.token_stats = {} # 清空上次的token统计
        st.rerun()

    # --- AI响应逻辑 (在rerun后执行，这样可以保证界面先显示出用户消息) ---
    if messages and messages[-1]["role"] == "user":
        last_user_message_content = messages[-1]["content"]
        
        logger.info(f"最后一条用户提问内容：{last_user_message_content}")
        
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            message_placeholder.markdown("🧠 思考中...")
            st.session_state.last_response_sources = [] # 重置溯源信息
            
            try:

                # --- 上下文构建 情景感知路由 (Context-aware Routing) ---
                context = ""
                
                # 步骤1：注入临时文件上下文
                if st.session_state.get("temp_file_text"):
                    logger.info("注入临时文件上下文。")
                    context += "--- 从您上传的临时文件中提取的相关信息如下 ---\n"
                    context += st.session_state.temp_file_text
                    context += "\n-------------------------------------------\n\n"
                    # 使用后立即清空，确保只对本次问答生效
                    st.session_state.temp_file_text = None
                
                # 步骤2：注入知识库上下文 和 背景资料
                # 【路由分支一】: 需要执行知识库搜索 (Search Path)
                if st.session_state.selected_kbs:
                    with st.spinner("正在检索知识库..."):
                        # 混合查询策略：保留原始查询，并加入重写后的查询  + rewritten_queries
                        search_queries = [last_user_message_content]
                        search_queries = list(dict.fromkeys(search_queries)) # 去重
                        logger.info(f"混合查询策略已启用: {search_queries}")
                        
                        kb_ids = [kb['id'] for kb in db_manager.list_knowledge_bases() if kb['name'] in st.session_state.selected_kbs]
                        
                        all_search_results = []
                        seen_contents = set()
                        
                        for query in search_queries:
                            results = kb_manager.search(query, kb_ids=kb_ids)
                            for res in results:
                                if res['content'] not in seen_contents:
                                    all_search_results.append(res)
                                    seen_contents.add(res['content'])
                        
                        if all_search_results:
                            context += "--- 从您的知识库中检索到的相关信息如下 ---\n"
                            st.session_state.last_response_sources = all_search_results
                            context_lines = []
                            for res in all_search_results:
                                source_info = f"【{res['citation_id']} | 来源: {res['metadata'].get('source', '未知')}】"
                                context_lines.append(f"{source_info}\n{res['content']}")
                            context += "\n".join(context_lines)
                            context += "-------------------------------------------\n"
                            
                    # 步骤3：注入通用背景资料
                    background_knowledge = db_manager.get_background_knowledge()
                    if background_knowledge: context += f"\n--- 通用背景资料 ---\n{background_knowledge}\n-------------------\n"
                
                    # --- 构建最终 Prompt ---
                    system_prompt_content = prompt_manager.render('system_prompt.jinja2', context=context)
                    
                else:
                    # 【路由分支二】: 直接回答 (Answer-Directly Path)
                    logger.info("路由决策: 直接回答 (闲聊或无知识库)。")
                    # 使用专为闲聊设计的、极其简洁的Prompt，避免Persona过载
                    system_prompt_content = prompt_manager.render('chitchat_prompt.jinja2', context=context)
                
                final_messages_to_send = [{"role": "system", "content": system_prompt_content}]
                final_messages_to_send.extend([{"role": m["role"], "content": m["content"]} for m in messages])
                
                # logger.info(f"加载前文所有的对话信息：{[{"role": m["role"], "content": m["content"]} for m in messages]}")
                
                # --- 调用LLM并处理响应 ---
                with st.spinner("正在生成回答..."):
                    full_response, stats = llm_service.chat_completion(
                        final_messages_to_send, 
                        topic_id=st.session_state.current_topic_id
                    )
                    
                st.session_state.token_stats = stats # 保存token统计信息

                if full_response:
                    message_placeholder.markdown(full_response, unsafe_allow_html=True)
                    db_manager.add_message(st.session_state.current_topic_id, "assistant", full_response)
                    
                    # 4. 检查是否需要自动生成标题
                    current_topic = db_manager.get_topic_by_id(st.session_state.current_topic_id)
                    # 只有在新对话的第一轮之后才触发
                    if current_topic and current_topic['title'].startswith("新对话 -") and len(messages) <= 2:
                        if auto_generate_title(st.session_state.current_topic_id, last_user_message_content, full_response):
                            st.rerun() # 生成标题后刷新，显示新标题
                        else:
                            st.rerun()
                    else:
                        st.rerun() # AI响应后，刷新以固化消息
                else:
                    message_placeholder.error("抱歉，获取AI回答时发生未知错误，请检查后台日志。")

            except Exception as e:
                # 捕获来自 llm_service 的错误并在UI上显示
                logger.error(f"AI响应生成失败: {e}", exc_info=True)
                error_message = f"请求AI服务时发生错误：\n\n`{str(e)}`\n\n请检查：\n1. `config.yaml`中的API密钥或服务地址是否正确。\n2. 网络连接是否正常。\n3. 后台日志以获取详细信息。"
                message_placeholder.error(error_message)

