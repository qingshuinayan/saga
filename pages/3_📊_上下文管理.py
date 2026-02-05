# 📜 saga/pages/3_📊_上下文管理.py

import streamlit as st
import pandas as pd
from utils.database import db_manager

st.set_page_config(page_title="上下文管理", page_icon="📊", layout="wide")
st.title("📊 上下文管理监控")
st.markdown("监控和管理对话的上下文摘要，确保长期对话的连贯性")

topics = db_manager.list_topics()
if not topics:
    st.info("暂无对话话题。")
    st.stop()

# --- 构建数据表格 ---
data = []
for topic in topics:
    stats = db_manager.get_conversation_stats(topic['id'])
    # 【已优化】从数据库获取摘要
    summary = topic['summary'] 
    
    data.append({
        "ID": topic['id'],
        "标题": topic['title'],
        "总消息数": stats['total_messages'],
        "对话轮次": stats['dialogue_rounds'],
        "是否有摘要": "✓" if summary else "✗",
        "最后更新": stats['last_updated'].split('.')[0] if stats['last_updated'] else "N/A" # 移除毫秒
    })
df = pd.DataFrame(data)

# --- 顶部统计指标 ---
st.subheader("全局统计")
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("总话题数", len(topics))
with col2:
    topics_with_summary = df["是否有摘要"].value_counts().get("✓", 0)
    st.metric("已生成摘要数", topics_with_summary)
with col3:
    avg_rounds = df["对话轮次"].mean()
    st.metric("平均对话轮次", f"{avg_rounds:.1f}")
with col4:
    # 使用配置中的token预算来判断是否需要摘要，这里用轮次做个近似
    long_convs = df[df["对话轮次"] > 10].shape[0]
    st.metric("长对话数 (>10轮)", long_convs)

st.divider()

# --- 单个话题详情与管理 ---
st.subheader("话题详情与摘要管理")
selected_topic_id = st.selectbox(
    "选择一个话题查看详情:",
    options=df["ID"].tolist(),
    format_func=lambda x: f"ID {x}: {df[df['ID'] == x]['标题'].iloc[0]}"
)

if selected_topic_id:
    # 获取选定话题的完整信息
    selected_topic = db_manager.get_topic_by_id(selected_topic_id)
    
    if selected_topic:
        col1, col2 = st.columns([1.5, 1])
        
        with col1:
            st.markdown(f"**话题详情: {selected_topic['title']}**")
            stats = db_manager.get_conversation_stats(selected_topic_id)
            st.info(f"""
            - **总消息数:** {stats['total_messages']}
            - **用户消息:** {stats['user_messages']}
            - **AI消息:** {stats['ai_messages']}
            - **对话轮次:** {stats['dialogue_rounds']}
            - **最后更新:** {stats['last_updated']}
            """)

            # 对话预览
            with st.expander("查看最近对话预览"):
                messages = db_manager.get_messages_by_topic(selected_topic_id)
                for msg in reversed(messages[-10:]): # 显示最新的
                    st.chat_message(msg["role"]).write(f"*{msg['timestamp'].split('.')[0]}* - {msg['content'][:150]}...")
        
        with col2:
            st.markdown("**摘要管理**")
            summary = selected_topic['summary']
            
            if summary:
                with st.expander("查看摘要", expanded=True):
                    st.markdown(summary)
                
                # 【已优化】清除摘要操作现在是更新数据库
                if st.button("🗑️ 清除摘要", use_container_width=True, help="清除后，系统会在下次对话时根据需要重新生成。"):
                    db_manager.update_topic_summary(selected_topic_id, None)
                    st.success("摘要已清除。")
                    st.rerun()
            else:
                st.warning("此话题尚未生成摘要。")
                st.caption("当对话长度超过Token预算时，系统会自动生成摘要。")

st.divider()

# --- 所有话题概览表格 ---
st.subheader("所有话题概览")
st.dataframe(df, use_container_width=True, hide_index=True)

