# 📜 saga/pages/5_🎭_角色提示词.py

import streamlit as st
from utils.config import config
from utils.database import db_manager
from utils.prompt_manager import prompt_manager
from utils.logging_config import logger

st.set_page_config(page_title="角色提示词", page_icon="🎭", layout="wide")

st.title("🎭 角色提示词管理")
st.markdown("自定义和管理系统的角色提示词。**提示词内容由可编辑部分和固定逻辑部分组成**，固定部分（上下文注入逻辑）不可修改。")

# 确保默认提示词已初始化
db_manager.init_default_prompts()

# --- 侧边栏：操作选择 ---
with st.sidebar:
    st.subheader("🔧 操作")
    action = st.radio(
        "选择操作",
        ["📋 查看提示词", "➕ 新建自定义角色", "✏️ 编辑现有角色"],
        label_visibility="collapsed"
    )

    st.divider()
    st.markdown("**提示类型**")
    st.caption("• `system` - 系统角色（专业问答）")
    st.caption("• `chitchat` - 闲聊角色（日常对话）")
    st.caption("• `custom` - 自定义角色")

# --- 操作：查看提示词列表 ---
if action == "📋 查看提示词":
    st.subheader("📋 所有角色提示词")

    # 获取所有提示词
    all_prompts = db_manager.list_system_prompts()

    if not all_prompts:
        st.info("暂无提示词")
    else:
        # 按类型分组
        prompts_by_type = {}
        for prompt in all_prompts:
            ptype = prompt['prompt_type']
            if ptype not in prompts_by_type:
                prompts_by_type[ptype] = []
            prompts_by_type[ptype].append(prompt)

        # 显示各类型提示词
        type_names = {
            'system': '🤖 系统角色（专业问答）',
            'chitchat': '💬 闲聊角色（日常对话）',
            'custom': '🎨 自定义角色'
        }

        for ptype, prompts in prompts_by_type.items():
            st.markdown(f"### {type_names.get(ptype, ptype)}")

            for prompt in prompts:
                with st.expander(f"{'✅' if prompt['is_active'] else '❌'} {prompt['display_name']} (`{prompt['name']}`)"):
                    col1, col2 = st.columns([3, 1])

                    with col1:
                        st.markdown(f"**名称**: `{prompt['name']}`")
                        st.markdown(f"**描述**: {prompt['description'] or '无'}")
                        st.markdown(f"**创建时间**: {prompt['created_at']}")
                        st.markdown(f"**更新时间**: {prompt['updated_at']}")

                        # 预览角色定义
                        with st.expander("📄 预览内容"):
                            st.markdown(prompt['role_definition'])
                            if prompt['skills']:
                                st.markdown("### Skills")
                                st.markdown(prompt['skills'])
                            if prompt['rules']:
                                st.markdown("### Rules")
                                st.markdown(prompt['rules'])

                    with col2:
                        st.markdown("**状态**")
                        if prompt['is_active']:
                            st.success("已激活")
                        else:
                            st.warning("未激活")

                        st.markdown("**操作**")
                        if prompt['name'] not in ['default_system', 'default_chitchat']:
                            if st.button(f"🗑️ 删除", key=f"del_{prompt['id']}", use_container_width=True):
                                if db_manager.delete_system_prompt(prompt['name']):
                                    st.success(f"已删除: {prompt['display_name']}")
                                    st.rerun()
                                else:
                                    st.error(f"删除失败")

# --- 操作：新建自定义角色 ---
elif action == "➕ 新建自定义角色":
    st.subheader("➕ 新建自定义角色")

    with st.form("create_prompt_form"):
        st.markdown("#### 基本信息")
        col1, col2 = st.columns(2)
        with col1:
            new_name = st.text_input(
                "角色标识符（英文字母、数字、下划线）",
                placeholder="my_custom_role",
                help="用于内部标识，必须唯一"
            )
        with col2:
            new_display_name = st.text_input(
                "显示名称",
                placeholder="我的自定义角色"
            )

        new_description = st.text_area("描述", placeholder="这个角色的用途是什么...")

        st.markdown("#### 角色定义")
        new_role = st.text_area(
            "角色定义（Role Definition）",
            placeholder="# Role: 你的角色名称\n\n## Profile\n- language: 中文\n- description: ...",
            height=200,
            help="定义角色的基本身份、背景、个性和专业领域"
        )

        st.markdown("#### 可选部分")
        with st.expander("📚 技能（Skills）", expanded=False):
            new_skills = st.text_area(
                "技能描述",
                placeholder="1. 技能1\n   - 详细说明\n2. 技能2\n   - 详细说明",
                height=150,
                help="描述角色的核心能力和技能组合"
            )

        with st.expander("📜 规则（Rules）", expanded=False):
            new_rules = st.text_area(
                "行为规则",
                placeholder="1. 基本原则：\n   - 规则1\n   - 规则2\n2. 行为准则：\n   - ...",
                height=150,
                help="定义角色必须遵守的行为准则和约束条件"
            )

        with st.expander("🔄 工作流程（Workflows）", expanded=False):
            new_workflows = st.text_area(
                "工作流程",
                placeholder="- 目标: ...\n- 步骤 1: ...\n- 步骤 2: ...\n- 预期结果: ...",
                height=150,
                help="定义角色处理任务的标准流程"
            )

        with st.expander("📤 输出格式（Output Format）", expanded=False):
            new_output_format = st.text_area(
                "输出格式规范",
                placeholder="1. 格式类型1：\n   - format: markdown\n   - structure: ...",
                height=150,
                help="定义角色输出内容的格式和结构要求（可选）"
            )

        submitted = st.form_submit_button("✅ 创建角色", use_container_width=True)

        if submitted:
            if not new_name or not new_display_name or not new_role:
                st.error("请填写必填字段：角色标识符、显示名称和角色定义")
            else:
                # 验证名称格式
                import re
                if not re.match(r'^[a-zA-Z0-9_]+$', new_name):
                    st.error("角色标识符只能包含字母、数字和下划线")
                else:
                    result = db_manager.add_system_prompt(
                        name=new_name,
                        display_name=new_display_name,
                        description=new_description,
                        prompt_type='custom',
                        role_definition=new_role,
                        skills=new_skills or None,
                        rules=new_rules or None,
                        workflows=new_workflows or None,
                        output_format=new_output_format or None
                    )

                    if result:
                        st.success(f"✅ 角色 '{new_display_name}' 创建成功！")
                        st.balloons()
                    else:
                        st.error(f"❌ 创建失败，角色标识符 '{new_name}' 可能已存在")

# --- 操作：编辑现有角色 ---
elif action == "✏️ 编辑现有角色":
    st.subheader("✏️ 编辑现有角色")

    # 获取所有可编辑的提示词
    all_prompts = db_manager.list_system_prompts()

    # 选择要编辑的提示词
    prompt_options = {f"{p['display_name']} ({p['name']})": p['name'] for p in all_prompts}
    selected_option = st.selectbox("选择要编辑的角色", options=list(prompt_options.keys()))

    if selected_option:
        selected_name = prompt_options[selected_option]
        prompt_data = db_manager.get_system_prompt_by_name(selected_name)

        if prompt_data:
            st.info(f"正在编辑: **{prompt_data['display_name']}** (`{prompt_data['name']}`)")

            # 如果是默认角色，显示警告
            if prompt_data['name'] in ['default_system', 'default_chitchat']:
                st.warning("⚠️ 这是默认角色，建议保留原始内容，创建自定义角色以满足不同需求。")

            with st.form("edit_prompt_form"):
                st.markdown("#### 基本信息")
                col1, col2 = st.columns(2)

                with col1:
                    # 角色标识符不可修改
                    st.text_input("角色标识符", value=prompt_data['name'], disabled=True)

                with col2:
                    edit_display_name = st.text_input("显示名称", value=prompt_data['display_name'])

                edit_description = st.text_area("描述", value=prompt_data['description'] or '', height=80)

                # 激活状态
                edit_is_active = st.checkbox("激活此角色", value=bool(prompt_data['is_active']))

                st.markdown("---")
                st.markdown("#### 角色定义（可编辑）")
                st.caption("💡 提示：上下文注入逻辑是固定的，无需在此处定义")

                edit_role = st.text_area(
                    "角色定义",
                    value=prompt_data['role_definition'],
                    height=250,
                    help="定义角色的基本身份、背景、个性和专业领域"
                )

                st.markdown("#### 可选部分")

                with st.expander("📚 技能（Skills）", expanded=bool(prompt_data.get('skills'))):
                    edit_skills = st.text_area(
                        "技能描述",
                        value=prompt_data.get('skills') or '',
                        height=150
                    )

                with st.expander("📜 规则（Rules）", expanded=bool(prompt_data.get('rules'))):
                    edit_rules = st.text_area(
                        "行为规则",
                        value=prompt_data.get('rules') or '',
                        height=150
                    )

                with st.expander("🔄 工作流程（Workflows）", expanded=bool(prompt_data.get('workflows'))):
                    edit_workflows = st.text_area(
                        "工作流程",
                        value=prompt_data.get('workflows') or '',
                        height=150
                    )

                with st.expander("📤 输出格式（Output Format）", expanded=bool(prompt_data.get('output_format'))):
                    edit_output_format = st.text_area(
                        "输出格式规范",
                        value=prompt_data.get('output_format') or '',
                        height=200
                    )

                col_submit, col_preview = st.columns(2)

                with col_submit:
                    submitted = st.form_submit_button("💾 保存修改", use_container_width=True)

                with col_preview:
                    preview = st.form_submit_button("👁️ 预览完整提示词", use_container_width=True)

                if submitted:
                    db_manager.update_system_prompt(
                        name=prompt_data['name'],
                        display_name=edit_display_name,
                        description=edit_description,
                        role_definition=edit_role,
                        skills=edit_skills or None,
                        rules=edit_rules or None,
                        workflows=edit_workflows or None,
                        output_format=edit_output_format or None,
                        is_active=1 if edit_is_active else 0
                    )
                    st.success(f"✅ 已保存对 '{edit_display_name}' 的修改")

                if preview:
                    # 构建预览数据
                    preview_data = {
                        'display_name': edit_display_name,
                        'role_definition': edit_role,
                        'skills': edit_skills or None,
                        'rules': edit_rules or None,
                        'workflows': edit_workflows or None,
                        'output_format': edit_output_format or None
                    }

                    # 渲染完整提示词（不含上下文）
                    full_prompt = prompt_manager.render_db_prompt(preview_data, context=None)

                    st.markdown("---")
                    st.markdown("### 📄 完整提示词预览")
                    st.markdown("**固定逻辑部分已自动添加在末尾**")
                    st.code(full_prompt, language="markdown")

                    # 预览带上下文的版本
                    st.markdown("---")
                    st.markdown("### 📄 带上下文的完整提示词预览")
                    sample_context = "这里是知识库检索到的示例内容..."
                    full_prompt_with_ctx = prompt_manager.render_db_prompt(preview_data, context=sample_context)
                    st.code(full_prompt_with_ctx, language="markdown")

# --- 页面底部说明 ---
st.divider()
st.caption("""
💡 **使用说明**：
- 每个提示词由多个部分组成，你可以根据需要自定义这些部分
- 固定逻辑部分（上下文注入）会在运行时自动添加，无需手动定义
- 建议为不同领域创建专门的角色，如"医疗健康专家"、"法律顾问"等
- 激活状态控制该角色是否可用，同一类型可以有多个激活角色
""")
