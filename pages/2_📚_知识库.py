# 📜 saga/pages/2_📚_知识库.py

import streamlit as st
import os
from datetime import datetime
import pandas as pd

# --- 内部模块 ---
from utils.config import config
from utils.database import db_manager
from utils.knowledge_base import kb_manager
from utils.logging_config import logger
from utils.llm_service import llm_service

# --- 页面基础设置 ---
st.set_page_config(page_title="知识库管理", page_icon="📚", layout="wide")
st.title("📚 知识库管理")
st.markdown("构建和检索您的个人知识体系")

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

# --- 辅助函数 ---
def refresh_page():
    """强制 Streamlit 重新运行页面"""
    st.rerun()

# --- 1. 通用背景资料 ---
with st.expander("通用背景资料 (作为所有对话的通用知识)", expanded=False):
    st.info("您可以在此输入或更新希望AI在所有对话中都能参考的通用背景信息，例如您的公司组织架构、部门职责、核心产品线等。")
    current_background_knowledge = db_manager.get_background_knowledge() or ""
    new_background_knowledge = st.text_area(
        "背景资料内容:", value=current_background_knowledge, height=250, label_visibility="collapsed"
    )
    if st.button("保存通用背景资料"):
        try:
            db_manager.update_background_knowledge(new_background_knowledge)
            st.success("通用背景资料已成功更新！")
            logger.info("通用背景资料已更新。")
        except Exception as e:
            st.error(f"保存失败: {e}")

st.divider()

# --- 2. 知识库管理与文件上传 ---
col1, col2 = st.columns([1, 1.5])

# --- 左侧列: 创建和选择知识库 ---
with col1:
    st.subheader("STEP 1: 创建或选择知识库")

    # 获取当前服务模式
    current_mode = config.get('llm_service.active_mode', 'external')
    mode_display = {
        'external': '🌐 外部API',
        'internal': '🏢 企业内网',
        'local': '💻 本地Ollama'
    }

    # 显示当前激活的向量模型
    active_embedding_model = llm_service.get_active_embedding_model_name()
    st.info(f"**当前服务模式**: {mode_display.get(current_mode, current_mode)}\n\n**当前向量模型**: `{active_embedding_model}`\n\n上传的文件将使用此模型进行索引。")

    kb_list = db_manager.list_knowledge_bases()

    # 过滤出与当前模式匹配的知识库
    compatible_kbs = [kb for kb in kb_list if kb.get("embedding_model") == active_embedding_model]
    incompatible_kbs = [kb for kb in kb_list if kb.get("embedding_model") and kb["embedding_model"] != active_embedding_model]

    # 显示未设置embedding_model的知识库警告
    unset_model_kbs = [kb for kb in kb_list if not kb.get("embedding_model")]
    if unset_model_kbs:
        with st.expander(f"⚠️ 未设置向量模型的知识库 ({len(unset_model_kbs)}个)", expanded=True):
            st.caption("以下知识库未设置向量模型，需要重新创建或手动修复：")
            for kb in unset_model_kbs:
                st.caption(f"• {kb['name']} (NULL)")
            st.info("建议：删除这些知识库后重新创建，系统会自动使用当前向量模型。")

    # 显示不兼容知识库的提示
    if incompatible_kbs:
        with st.expander(f"⚠️ 其他模式的知识库 ({len(incompatible_kbs)}个)", expanded=False):
            st.caption("以下知识库使用不同的向量模型，在当前模式下无法使用：")
            for kb in incompatible_kbs:
                st.caption(f"• {kb['name']} (`{kb['embedding_model']}`)")

    # 只显示兼容的知识库
    kb_names = [kb["name"] for kb in compatible_kbs]

    if kb_names:
        selected_kb_name = st.selectbox(
            "选择一个要操作的知识库:", options=kb_names, index=0 if kb_names else None, placeholder="请先创建或选择一个知识库"
        )
        selected_kb_id = next((kb["id"] for kb in compatible_kbs if kb["name"] == selected_kb_name), None)
    else:
        st.selectbox(
            "选择一个要操作的知识库:", options=[], placeholder="当前模式下没有可用的知识库"
        )
        selected_kb_name = None
        selected_kb_id = None

        if incompatible_kbs:
            st.warning("当前服务模式下没有兼容的知识库。请切换服务模式或创建新知识库。")

    with st.form("new_kb_form", clear_on_submit=True):
        st.markdown("**或者，创建一个新的知识库:**")
        new_kb_name = st.text_input("新知识库名称")
        new_kb_desc = st.text_area("知识库描述 (可选)", height=100)
        if st.form_submit_button("创建知识库"):
            if not new_kb_name:
                st.error("知识库名称不能为空！")
            elif new_kb_name in kb_names:
                st.warning("该知识库名称已存在！")
            else:
                # 创建知识库时，自动使用当前激活的向量模型
                db_manager.add_knowledge_base(
                    name=new_kb_name,
                    description=new_kb_desc,
                    embedding_model=active_embedding_model
                )
                st.success(f"知识库 '{new_kb_name}' 创建成功！使用向量模型: `{active_embedding_model}`")
                refresh_page()

# --- 右侧列: 上传文件 ---
with col2:
    st.subheader("STEP 2: 上传文件到知识库")
    
    if not selected_kb_name:
        st.warning("请先在左侧选择或创建一个知识库。")
    else:
        st.success(f"当前操作的知识库: **{selected_kb_name}**")
        
        # --- 定义处理文件的回调函数 ---
        def handle_file_processing():
            # 使用动态key来获取当前上传的文件
            uploader_widget_key = f"kb_file_uploader_{st.session_state.uploader_key}"
            uploaded_files = st.session_state.get(uploader_widget_key, [])
            if not uploaded_files:
                st.warning("请先选择要上传的文件。")
                return

            uploads_dir = config.get('paths.uploads')
            os.makedirs(uploads_dir, exist_ok=True)
            
            with st.expander("文件处理进度", expanded=True):
                for i, uploaded_file in enumerate(uploaded_files):
                    st.info(f"正在处理文件 {i+1}/{len(uploaded_files)}: '{uploaded_file.name}'")
                    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                    safe_filename = f"{timestamp}_{uploaded_file.name}"
                    file_path = os.path.join(uploads_dir, safe_filename)
                    
                    try:
                        with open(file_path, "wb") as f: f.write(uploaded_file.getbuffer())
                        
                        file_id = db_manager.add_file_to_kb(
                            kb_id=selected_kb_id,
                            file_name=uploaded_file.name,
                            file_path=file_path,
                            embedding_model=active_embedding_model
                        )
                        
                        if file_id is None:
                            st.warning(f"文件 '{uploaded_file.name}' 已存在于数据库中，跳过。")
                            continue
                        
                        kb_manager.add_document(
                            file_path=file_path, 
                            kb_id=selected_kb_id, 
                            file_id=file_id
                        )
                        st.success(f"✅ 文件 '{uploaded_file.name}' 已成功处理！")
                    except Exception as e:
                        st.error(f"❌ 处理文件 '{uploaded_file.name}' 时发生错误: {e}")
                        logger.error(f"处理文件 '{uploaded_file.name}' 失败: {e}", exc_info=True)
                
                st.success("所有文件处理完成！")
            
            # 不直接修改state，而是增加key的版本号，以销毁并重建控件
            st.session_state.uploader_key += 1
        
        # --- 文件上传控件 ---
        # 使用动态key
        current_uploader_key = f"kb_file_uploader_{st.session_state.uploader_key}"
        
        st.file_uploader(
            "支持 PDF, TXT, MD, PNG, JPG 等格式。可一次上传多个文件。",
            type=['pdf', 'txt', 'md', 'png', 'jpg', 'jpeg'],
            accept_multiple_files=True,
            key=current_uploader_key # 使用动态key
        )
        
        # --- 处理按钮，使用 on_click 回调 ---
        st.button(
            "开始处理上传的文件", 
            on_click=handle_file_processing,
            disabled=(not st.session_state.get(current_uploader_key)), # 禁用状态也依赖动态key
            use_container_width=True
        )

st.divider()

# --- 3. 知识库内容展示 (完整重构) ---
st.subheader("知识库内容概览")
if not selected_kb_name:
    st.info("请在上方选择一个知识库以查看其内容。")
else:
    st.markdown(f"当前查看的知识库: **{selected_kb_name}**")
    
    # 从数据库获取该知识库下的所有文件
    files_in_kb = db_manager.list_files_in_kb(selected_kb_id)
    
    if not files_in_kb:
        st.info("该知识库中还没有任何文件。")
    else:
        # --- 【新增】风险提示，告知用户模型不匹配的文件 ---
        files_with_current_model = [f for f in files_in_kb if f["embedding_model"] == active_embedding_model]
        mismatched_files_count = len(files_in_kb) - len(files_with_current_model)
        
        if mismatched_files_count > 0:
            st.warning(
                f"**注意:** 该知识库中有 **{mismatched_files_count}** 个文件是使用其他向量模型索引的。"
                f"在当前 **'{active_embedding_model}'** 模式下，这些文件将 **不会** 被搜索到。"
                "如需搜索，请切换到对应的系统设置模式，或重新上传这些文件以使用当前模型建立索引。"
            )

        # --- 【已优化】使用DataFrame展示文件列表，并增加模型匹配状态 ---
        display_data = []
        for f in files_in_kb:
            is_active = (f["embedding_model"] == active_embedding_model)
            display_data.append({
                "文件名": f["file_name"],
                "状态": f["status"],
                "向量数": f["vector_count"],
                "索引模型": f["embedding_model"],
                "可用于当前搜索": "✅" if is_active and f["status"] == 'completed' else "❌",
                "上传时间": datetime.strptime(f["uploaded_at"], '%Y-%m-%d %H:%M:%S.%f' if '.' in f["uploaded_at"] else '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M'),
            })

        df = pd.DataFrame(display_data)
        
        df['id'] = [f['id'] for f in files_in_kb] # 将文件ID加入DataFrame
        
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "文件名": st.column_config.TextColumn(width="large"),
                "可用于当前搜索": st.column_config.TextColumn(help="文件是否使用当前激活的向量模型索引，并已完成处理。")
            }
        )
        
        st.markdown("**文件操作**")
        selected_file_id_to_delete = st.selectbox(
            "选择要删除的文件:", 
            options=[(f['file_name'], f['id']) for f in files_in_kb],
            format_func=lambda x: x[0],
            index=None,
            placeholder="选择一个文件..."
        )

        if selected_file_id_to_delete:
            file_name, file_id = selected_file_id_to_delete
            if st.button(f"确认删除文件: '{file_name}'", type="primary", use_container_width=True):
                with st.spinner(f"正在删除 '{file_name}' 及其相关知识..."):
                    # 1. 获取文件详情
                    file_details = db_manager.get_file_details(file_id)
                    if not file_details:
                        st.error("找不到文件详情，无法删除。")
                        st.stop()
                    
                    kb_id = file_details['kb_id']
                    embedding_model = file_details['embedding_model']

                    # 2. 从ChromaDB删除向量
                    kb_manager.delete_document(kb_id, file_id, embedding_model)
                    
                    # 3. 从SQLite删除文件记录
                    db_manager.delete_file_from_kb(file_id)
                    
                st.success(f"文件 '{file_name}' 已被彻底从知识库中移除。")
                st.rerun()
