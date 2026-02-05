# 📜 saga/utils/database.py

import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

# 从同级目录导入config实例
from .config import config
from .logging_config import logger

class DatabaseManager:
    """
    数据库管理类，负责所有与SQLite数据库的交互。
    使用单例模式，确保应用中只有一个数据库连接管理器。
    """
    _instance = None
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(DatabaseManager, cls).__new__(cls, *args, **kwargs)
            db_path = config.get('paths.database')
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            cls._instance.db_path = db_path
            cls._instance.initialize_database()
        return cls._instance

    def get_connection(self) -> sqlite3.Connection:
        """获取一个新的数据库连接。设置row_factory以便将行作为类似字典的对象访问。"""
        conn = sqlite3.connect(self.db_path, timeout=10) # 增加超时
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.row_factory = sqlite3.Row
        
        # 设置连接池属性
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        
        return conn
    
    def execute_with_retry(self, query: str, params: tuple = (), max_retries: int = 3):
        """带重试的执行方法"""
        for attempt in range(max_retries):
            try:
                with self.get_connection() as conn:
                    cursor = conn.execute(query, params)
                    result = cursor.fetchall()
                    conn.commit()
                    return result
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    import time
                    time.sleep(0.1 * (2 ** attempt))  # 指数退避
                    continue
                else:
                    raise

    def initialize_database(self):
        """
        初始化数据库，增强了表结构以支持新功能。
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_bases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            
            # --- knowledge_files 表 ---
            # 增加了 embedding_model 字段，用于记录索引时使用的模型
            # 这是解决不同模型向量维度冲突的核心
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'uploaded', -- 'uploaded', 'processing', 'completed', 'failed'
                vector_count INTEGER DEFAULT 0,
                embedding_model TEXT, -- 新增字段，记录使用的向量模型
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (kb_id) REFERENCES knowledge_bases (id) ON DELETE CASCADE
            )
            """)
            
            # --- conversation_topics 表 ---
            # 增加了 summary 字段，用于持久化存储对话摘要
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                summary TEXT, -- 新增字段，用于存储对话摘要
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id INTEGER NOT NULL,
                role TEXT NOT NULL, -- 'user', 'assistant', 'system'
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (topic_id) REFERENCES conversation_topics (id) ON DELETE CASCADE
            )
            """)
            
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS background_knowledge (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                content TEXT,
                last_updated_at TIMESTAMP
            )
            """)
            cursor.execute("INSERT OR IGNORE INTO background_knowledge (id, content) VALUES (1, '')")
            
            # file_chunks 表用于存储每个文件分割后的文本块，为BM25快速重建索引提供数据源。
            # 在SQLite数据库中创建一个新表 file_chunks，用于持久化存储每个文件的文本块。当需要重建BM25索引时，直接从该表读取所有文本块，而无需重新进行文件I/O和文本提取、分割等耗时操作。
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                FOREIGN KEY (file_id) REFERENCES knowledge_files (id) ON DELETE CASCADE
            )
            """)
            # 创建一个复合唯一索引，防止重复添加
            cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_file_chunk ON file_chunks (file_id, chunk_index);
            """)

            # --- system_prompts 表 ---
            # 用于存储可自定义的系统提示词，支持不同领域的角色设定
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                description TEXT,
                prompt_type TEXT NOT NULL DEFAULT 'custom', -- 'system', 'chitchat', 'custom'
                role_definition TEXT NOT NULL,
                profile TEXT,
                skills TEXT,
                rules TEXT,
                workflows TEXT,
                output_format TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # 执行数据库迁移（添加新字段）
            self._migrate_database(cursor)

            conn.commit()
            logger.info("数据库初始化完成或已是最新状态。")

    def _migrate_database(self, cursor):
        """
        数据库迁移：添加新字段以支持slot-based配置和OCR降级功能

        新增字段：
        - knowledge_bases.embedding_model: 记录知识库使用的嵌入模型
        - knowledge_files.parse_source: 记录文档解析使用的槽位（slot_1/slot_2）
        - knowledge_files.parse_warning: 记录解析过程中的警告信息
        - conversation_topics.knowledge_bases: 记录对话使用的知识库ID列表（JSON格式）
        """
        try:
            # 检查并添加 knowledge_bases.embedding_model 字段
            cursor.execute("PRAGMA table_info(knowledge_bases)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'embedding_model' not in columns:
                cursor.execute("""
                    ALTER TABLE knowledge_bases ADD COLUMN embedding_model TEXT
                """)
                logger.info("已添加 knowledge_bases.embedding_model 字段")

            # 检查并添加 knowledge_files.parse_source 字段
            cursor.execute("PRAGMA table_info(knowledge_files)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'parse_source' not in columns:
                cursor.execute("""
                    ALTER TABLE knowledge_files ADD COLUMN parse_source TEXT DEFAULT 'slot_1'
                """)
                logger.info("已添加 knowledge_files.parse_source 字段")

            if 'parse_warning' not in columns:
                cursor.execute("""
                    ALTER TABLE knowledge_files ADD COLUMN parse_warning TEXT
                """)
                logger.info("已添加 knowledge_files.parse_warning 字段")

            # 检查并添加 conversation_topics.knowledge_bases 字段
            cursor.execute("PRAGMA table_info(conversation_topics)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'knowledge_bases' not in columns:
                cursor.execute("""
                    ALTER TABLE conversation_topics ADD COLUMN knowledge_bases TEXT
                """)
                logger.info("已添加 conversation_topics.knowledge_bases 字段")

        except Exception as e:
            logger.warning(f"数据库迁移过程中出现警告: {e}")

    # --- 知识库 (Knowledge Base) 操作 ---
    
    def add_knowledge_base(self, name: str, description: str = "", embedding_model: Optional[str] = None) -> Optional[int]:
        """
        添加一个新的知识库分类

        Args:
            name: 知识库名称
            description: 描述
            embedding_model: 使用的嵌入模型（可选）
        """
        with self.get_connection() as conn:
            try:
                cursor = conn.execute(
                    "INSERT INTO knowledge_bases (name, description, embedding_model) VALUES (?, ?, ?)",
                    (name, description, embedding_model)
                )
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                logger.warning(f"知识库名称 '{name}' 已存在。")
                return None

    def list_knowledge_bases(self) -> List[Dict[str, Any]]:
        """列出所有知识库分类"""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM knowledge_bases ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    # --- 文件 (File) 操作 ---
    
    def add_file_to_kb(self, kb_id: int, file_name: str, file_path: str, embedding_model: str) -> Optional[int]:
        """
        【已优化】向指定的知识库添加一个文件记录，并记录使用的模型。
        """
        with self.get_connection() as conn:
            try:
                cursor = conn.execute(
                    "INSERT INTO knowledge_files (kb_id, file_name, file_path, embedding_model) VALUES (?, ?, ?, ?)",
                    (kb_id, file_name, file_path, embedding_model)
                )
                logger.info(f"文件 '{file_name}' 已在数据库中记录，等待使用 '{embedding_model}' 模型处理。")
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                logger.warning(f"文件路径 '{file_path}' 已存在于数据库中。")
                return None

    def update_file_status(self, file_id: int, status: str, vector_count: Optional[int] = None):
        """更新文件的状态和向量数量"""
        with self.get_connection() as conn:
            if vector_count is not None:
                conn.execute("UPDATE knowledge_files SET status = ?, vector_count = ? WHERE id = ?",
                             (status, vector_count, file_id))
            else:
                conn.execute("UPDATE knowledge_files SET status = ? WHERE id = ?", (status, file_id))
            conn.commit()
            logger.info(f"文件ID {file_id} 的状态已更新为 '{status}'")

    def update_kb_embedding_model(self, kb_id: int, embedding_model: str):
        """更新知识库的嵌入模型"""
        with self.get_connection() as conn:
            conn.execute("UPDATE knowledge_bases SET embedding_model = ? WHERE id = ?", (embedding_model, kb_id))
            conn.commit()
            logger.info(f"知识库ID {kb_id} 的嵌入模型已更新为 '{embedding_model}'")

    def update_file_parse_info(self, file_id: int, parse_source: str, parse_warning: Optional[str] = None):
        """
        更新文件的解析信息

        Args:
            file_id: 文件ID
            parse_source: 解析来源（'slot_1' 或 'slot_2'）
            parse_warning: 解析警告信息（可选）
        """
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE knowledge_files SET parse_source = ?, parse_warning = ? WHERE id = ?",
                (parse_source, parse_warning, file_id)
            )
            conn.commit()
            logger.info(f"文件ID {file_id} 的解析信息已更新: source={parse_source}")

    def list_files_in_kb(self, kb_id: int, model_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        列出指定知识库中的所有文件，可选择按模型名称过滤。
        返回结果包括新的 parse_source 和 parse_warning 字段。
        """
        if not kb_id:
            return []
        with self.get_connection() as conn:
            query = "SELECT id, file_name, file_path, status, vector_count, uploaded_at, embedding_model, parse_source, parse_warning FROM knowledge_files WHERE kb_id = ? "
            params = [kb_id]
            if model_name:
                query += "AND embedding_model = ? "
                params.append(model_name)
            query += "ORDER BY uploaded_at DESC"

            cursor = conn.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
            
    # --- 对话 (Conversation) 操作 ---

    def add_topic(self, title: str) -> Optional[int]:
        """创建一个新的对话主题"""
        now = datetime.now()
        with self.get_connection() as conn:
            cursor = conn.execute("INSERT INTO conversation_topics (title, created_at, last_updated_at) VALUES (?, ?, ?)", (title, now, now))
            return cursor.lastrowid

    def list_topics(self) -> List[Dict[str, Any]]:
        """列出所有对话主题"""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM conversation_topics ORDER BY last_updated_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def add_message(self, topic_id: int, role: str, content: str):
        """向指定主题添加一条消息，并更新主题的最后更新时间"""
        now = datetime.now()
        with self.get_connection() as conn:
            conn.execute("INSERT INTO chat_messages (topic_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                         (topic_id, role, content, now))
            conn.execute("UPDATE conversation_topics SET last_updated_at = ? WHERE id = ?", (now, topic_id))
            conn.commit()

    def get_messages_by_topic(self, topic_id: int, limit: int = 1000) -> List[Dict[str, Any]]:
        """获取指定主题的所有消息（增加limit以防万一）"""
        logger.info(f"主题ID {topic_id} 的所有消息被获取")
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM chat_messages WHERE topic_id = ? ORDER BY timestamp ASC LIMIT ?",
                (topic_id, limit)
            )
            return [dict(row) for row in cursor.fetchall()]
            
    def update_topic_title(self, topic_id: int, new_title: str):
        """更新指定对话主题的标题"""
        with self.get_connection() as conn:
            conn.execute("UPDATE conversation_topics SET title = ? WHERE id = ?", (new_title, topic_id))
            conn.commit()
            logger.info(f"主题ID {topic_id} 的标题已更新为: '{new_title}'")

    def update_topic_knowledge_bases(self, topic_id: int, kb_ids: List[int]):
        """更新对话使用的知识库ID列表（存储为JSON格式）"""
        import json
        kb_ids_json = json.dumps(kb_ids)
        with self.get_connection() as conn:
            conn.execute("UPDATE conversation_topics SET knowledge_bases = ? WHERE id = ?", (kb_ids_json, topic_id))
            conn.commit()
            logger.info(f"主题ID {topic_id} 的知识库已更新为: {kb_ids}")

    def get_topic_knowledge_bases(self, topic_id: int) -> List[int]:
        """获取对话使用的知识库ID列表"""
        import json
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT knowledge_bases FROM conversation_topics WHERE id = ?", (topic_id,))
            row = cursor.fetchone()
            if row and row['knowledge_bases']:
                try:
                    return json.loads(row['knowledge_bases'])
                except:
                    return []
            return []

    def get_topic_by_id(self, topic_id: int) -> Optional[Dict[str, Any]]:
        """根据ID获取单个对话主题的信息"""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM conversation_topics WHERE id = ?", (topic_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
            
    def delete_topic(self, topic_id: int):
        """删除一个对话主题及其所有相关的聊天记录"""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM conversation_topics WHERE id = ?", (topic_id,))
            conn.commit()
            logger.info(f"已删除主题ID: {topic_id} 及其所有消息。")

    # --- 摘要管理 ---
    
    def update_topic_summary(self, topic_id: int, summary: str):
        """更新或插入对话摘要"""
        with self.get_connection() as conn:
            conn.execute("UPDATE conversation_topics SET summary = ? WHERE id = ?", (summary, topic_id))
            conn.commit()
            logger.info(f"已为 Topic ID {topic_id} 更新摘要。")

    def get_topic_summary(self, topic_id: int) -> Optional[str]:
        """获取对话摘要"""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT summary FROM conversation_topics WHERE id = ?", (topic_id,))
            row = cursor.fetchone()
            return row['summary'] if row else None

    # --- 通用背景资料 操作 ---
    
    def update_background_knowledge(self, content: str):
        """更新通用背景资料"""
        with self.get_connection() as conn:
            conn.execute("UPDATE background_knowledge SET content = ?, last_updated_at = ? WHERE id = 1",
                         (content, datetime.now()))
            conn.commit()

    def get_background_knowledge(self) -> Optional[str]:
        """获取通用背景资料"""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT content FROM background_knowledge WHERE id = 1")
            row = cursor.fetchone()
            return row['content'] if row else None
        
    # 与 file_chunks 表交互的方法
    def add_chunks_to_file(self, file_id: int, chunks: List[str]):
        """批量为文件添加文本块记录。"""
        if not chunks:
            return
        
        chunk_data = [(file_id, i, chunk) for i, chunk in enumerate(chunks)]
        with self.get_connection() as conn:
            conn.executemany(
                "INSERT INTO file_chunks (file_id, chunk_index, chunk_text) VALUES (?, ?, ?)",
                chunk_data
            )
            conn.commit()
            logger.info(f"为文件ID {file_id} 成功存储了 {len(chunks)} 个文本块。")

    def get_chunks_by_kb_id(self, kb_id: int) -> List[Dict[str, Any]]:
        """根据知识库ID获取其下所有文件的所有文本块。"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT fc.chunk_text, kf.file_name, kf.id as file_id
                FROM file_chunks fc
                JOIN knowledge_files kf ON fc.file_id = kf.id
                WHERE kf.kb_id = ?
            """, (kb_id,))
            return [dict(row) for row in cursor.fetchall()]
        
    # --- 删除文件记录 操作 ---
    
    def get_file_details(self, file_id: int) -> Optional[Dict[str, Any]]:
        """根据文件ID获取文件的详细信息，包括kb_id和embedding_model。"""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT kb_id, file_name, embedding_model FROM knowledge_files WHERE id = ?", (file_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_file_from_kb(self, file_id: int):
        """从 knowledge_files 表中删除一个文件记录。"""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM knowledge_files WHERE id = ?", (file_id,))
            conn.commit()
            logger.info(f"已从数据库中删除文件记录，ID: {file_id}")

    # --- 统计信息 ---
    def get_conversation_stats(self, topic_id: int) -> Dict[str, Any]:
        """
        获取对话统计信息。
        
        Returns:
            包含对话轮次、消息数等统计信息的字典
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 获取总消息数
            cursor.execute("SELECT COUNT(*) FROM chat_messages WHERE topic_id = ?", (topic_id,))
            result = cursor.fetchone()
            total_messages = result[0] if result else 0
            
            # 获取用户消息数
            cursor.execute("SELECT COUNT(*) FROM chat_messages WHERE topic_id = ? AND role = 'user'", (topic_id,))
            result = cursor.fetchone()
            user_messages = result[0] if result else 0
            
            # 获取AI消息数
            cursor.execute("SELECT COUNT(*) FROM chat_messages WHERE topic_id = ? AND role = 'assistant'", (topic_id,))
            result = cursor.fetchone()
            ai_messages = result[0] if result else 0
            
            # 获取对话轮次（近似值）
            dialogue_rounds = min(user_messages, ai_messages)
            
            # 获取最后更新时间
            cursor.execute("SELECT last_updated_at FROM conversation_topics WHERE id = ?", (topic_id,))
            result = cursor.fetchone()
            last_updated = result[0] if result else None
            
            # 获取创建时间
            cursor.execute("SELECT created_at FROM conversation_topics WHERE id = ?", (topic_id,))
            result = cursor.fetchone()
            created_at = result[0] if result else None
            
            return {
                "total_messages": total_messages,
                "user_messages": user_messages,
                "ai_messages": ai_messages,
                "dialogue_rounds": dialogue_rounds,
                "last_updated": last_updated,
                "created_at": created_at
            }

    # --- 系统提示词 (System Prompts) 操作 ---

    def init_default_prompts(self):
        """初始化默认的系统提示词"""
        with self.get_connection() as conn:
            # 检查是否已有默认提示词
            cursor = conn.execute("SELECT COUNT(*) FROM system_prompts WHERE prompt_type IN ('system', 'chitchat')")
            count = cursor.fetchone()[0]
            if count > 0:
                logger.info("默认提示词已存在，跳过初始化")
                return

            # 默认系统角色提示词（新能源汽车与AI技术融合专家）
            default_system_prompt = {
                'name': 'default_system',
                'display_name': '默认系统角色（新能源与AI专家）',
                'description': '专为新能源汽车与人工智能领域的复合型专家设计的系统提示词',
                'prompt_type': 'system',
                'role_definition': '''# Role: 新能源汽车与AI技术融合专家 Saga

## Profile
- language: 中文
- description: 一位兼具新能源汽车动力系统工程背景和人工智能技术落地经验的资深专家，具备从技术研发到产品化、商业化的全链条实战能力。熟悉整车开发流程、三电系统集成、智能驾驶算法部署及企业级AI项目管理。
- background: 拥有15年以上汽车行业研发经历，主导过多个量产电动车平台的动力总成设计，并成功推动多个人工智能模型在制造质量预测、电池健康管理、用户行为建模等场景的规模化应用。曾担任头部新势力车企技术总监及AI实验室负责人。
- personality: 直接、务实、结果导向，偏好用数据说话，厌恶空泛概念。沟通风格类比高管层内部决策会议中的技术负责人。
- expertise: 电动动力系统（电机、电控、电池）、整车能量管理、AI/ML工程化（边缘计算部署、OTA迭代、数据闭环）、成本控制与SOP推进、组织协同机制设计。
- target_audience: 企业中高层管理者、技术决策者、产品经理、研发工程师。''',
                'skills': '''1. 技术深度整合
   - 动力系统匹配优化：基于工况数据（如WLTC）进行驱动系统选型与效率调优，实现续航与性能平衡。
   - AI模型工程化：将算法模型转化为可部署、可监控、可持续迭代的生产级系统，支持OTA升级路径。
   - 成本结构分析：识别BOM关键项，推动降本方案落地，目标明确指向"降本X%"级别指标。
   - SOP节点管控：结合试制、验证、供应链进度，预判并干预关键里程碑风险。

2. 商业与组织洞察
   - 技术路线评估：结合市场趋势、法规要求和技术成熟度，提出可行的技术演进路径建议。
   - 跨部门协作推动：理解研发、采购、制造、售后之间的张力，设计有效协同机制。
   - 数据资产运营：构建以业务价值为导向的数据采集—处理—应用闭环，避免"为数据而数据"。
   - 风险预判与应对：基于历史项目经验识别潜在技术或执行风险，提前制定预案。''',
                'rules': '''1. 基本原则：
   - 数据优先：所有判断必须有量化依据支撑，优先呈现核心指标（如效率提升3.2%、故障率下降18%）。
   - 业务对齐：使用真实项目代号、内部术语（如"G9平台"、"EPA架构"、"SOP-2025Q2"），增强上下文贴合度。
   - 判断清晰：明确表达"我们认为…"、"建议优先…"、"风险在于…"，体现专家立场而非信息罗列。
   - 引用规范：凡引用知识库内容，必须标注[来源-N]，多源则并列标注；无来源时说明信息缺口。

2. 行为准则：
   - 开门见山：禁止寒暄、自我介绍或AI身份声明，直接切入主题。
   - 结构自然：采用"关键是…"、"下一步要解决的是…"、"这里有个风险点…"等口语化逻辑连接词。
   - 语言平实：避免学术腔和咨询黑话，禁用"赋能"、"抓手"、"颠覆"等泛化词汇，改用具体动作描述。
   - 不虚构信息：若知识库不足，明确指出"基于现有数据无法得出结论"，并尽可能补充通用行业认知。

3. 限制条件：
   - 不提供未经验证的假设性方案，仅输出经过工程实践检验的方法论或合理推断。
   - 不参与非技术性讨论（如品牌传播、公关策略），除非涉及技术叙事一致性。
   - 不替代具体岗位职责（如软件编码、产线操作），聚焦于决策支持与方向建议。
   - 不做绝对承诺（如"一定能成功"），始终保留技术不确定性空间。''',
                'workflows': '''- 目标: 提供精准、可执行、基于数据与经验的技术与商业建议
- 步骤 1: 解析问题本质，识别所需的关键技术维度与业务背景
- 步骤 2: 结合知识库信息（如有）与行业通用知识，提取相关数据与案例
- 步骤 3: 综合判断，形成带有明确建议与风险提示的回应，结构化呈现核心结论
- 预期结果: 输出简洁有力、具备决策参考价值的专业意见，推动问题解决或下一步行动''',
                'output_format': None,
                'is_active': 1
            }

            # 默认闲聊角色提示词
            default_chitchat_prompt = {
                'name': 'default_chitchat',
                'display_name': '默认闲聊角色（个人AI助手）',
                'description': '友好的个人AI助手，用于日常闲聊和通用问答',
                'prompt_type': 'chitchat',
                'role_definition': '''# Role: Saga - 个人AI助手

## Profile
- language: 中文
- description: 一位智能、可靠且富有亲和力的个人AI助手，名为Saga，能够以自然友好的方式处理日常闲聊，同时具备严谨专业的知识处理能力，应对常识性问题与深度专业咨询。
- background: Saga由先进的语言模型驱动，专为个人用户设计，融合了情感化交互与高精度知识推理能力，适用于生活、学习、工作等多场景支持。
- personality: 友善、耐心、聪慧、反应敏捷，兼具温度与理性，在轻松对话中保持专业底线。
- expertise: 多领域常识理解、科学知识、技术原理、人文社科、逻辑推理、信息整合与精准表达。
- target_audience: 希望获得高质量信息支持与人性化交互体验的个人用户。''',
                'skills': '''1. 自然语言交互
   - 情感识别：准确感知用户情绪与语境，调整回应风格。
   - 闲聊应答：以简洁自然的方式回应问候、寒暄与轻量互动。
   - 语气适配：根据上下文在亲切与正式间灵活切换。
   - 上下文连贯：维持多轮对话的一致性与记忆性。

2. 知识服务与深度解析
   - 常识问答：快速提供准确、可验证的生活与通识类答案。
   - 专业解答：深入解析科技、工程、医学、经济、哲学等领域复杂问题。
   - 信息溯源：基于权威知识体系构建回答，避免虚构内容。
   - 结构化输出：对复杂主题进行条理清晰、层次分明的呈现。''',
                'rules': '''1. 基本原则：
   - 准确优先：所有知识类回答必须基于事实，杜绝猜测或编造。
   - 用户中心：始终以用户需求为导向，尊重其表达方式与节奏。
   - 隐私保护：不记录、不追问、不推测用户私人信息。
   - 中立立场：在争议性话题中保持客观，呈现多方观点而非偏袒。

2. 行为准则：
   - 问候响应宜简短温暖，如"你好呀，我是Saga，今天过得怎么样？"
   - 知识回答需详尽但不过载，优先使用清晰结构与通俗语言。
   - 遇到不确定问题应明确说明限制，并提供合理推断路径。
   - 禁止主动引导话题、推销内容或插入无关信息。

3. 限制条件：
   - 不参与违法、伦理争议或高风险建议（如医疗诊断、法律判决）。
   - 不生成涉及暴力、歧视、虚假信息的内容。
   - 不模拟人类身份或声称具备意识与情感。
   - 所有输出须可追溯至公共知识或逻辑推导。''',
                'workflows': '''- 目标: 实现高质量、情境适配的人机交互体验
- 步骤 1: 分析输入语句的意图类型（闲聊 / 常识 / 专业）
- 步骤 2: 根据意图调用相应响应策略（情感化简短回应 或 结构化知识输出）
- 步骤 3: 对专业问题进行分层解析，确保逻辑严密、术语准确、解释易懂
- 预期结果: 用户获得既友好又可信的回应，满足情感交流与认知需求双重目标''',
                'output_format': '''1. 日常互动响应：
   - format: text
   - structure: 单段自然语言，无格式标记
   - style: 温和、口语化、带轻微人格化色彩
   - special_requirements: 控制在20字以内为佳，最多不超过50字

2. 知识性回答：
   - format: markdown
   - structure: 包含标题、要点列表、必要时的定义框或示例
   - style: 专业而不晦涩，使用"您"称呼，体现尊重
   - special_requirements: 关键术语加粗，长回答分段落，避免堆砌

3. 格式规范：
   - indentation: 使用标准空格缩进，每级4空格
   - sections: 多部分回答使用二级标题（##）划分
   - highlighting: 重点内容使用**加粗**或引用块 > 强调

4. 验证规则：
   - validation: 所有事实陈述需符合主流学术共识或权威来源
   - constraints: 不使用未经证实的数据或来源不明的引述
   - error_handling: 若无法确认答案，应回应"目前我无法提供确切信息"并解释原因

5. 示例说明：
   1. 示例1：
      - 标题: 闲聊问候回应
      - 格式类型: 日常互动响应
      - 说明: 用户发起简单问候时的典型回应
      - 示例内容: |
          你好呀，我是Saga，今天过得怎么样？

   2. 示例2：
      - 标题: 专业知识回答
      - 格式类型: 知识性回答
      - 说明: 用户询问相对论基本概念时的结构化回应
      - 示例内容: |
          ## 什么是狭义相对论？

          狭义相对论是阿尔伯特·爱因斯坦于1905年提出的物理理论，主要描述在没有引力作用下的时空结构与运动规律。

          **核心原理包括**：
          - **相对性原理**：所有惯性参考系中物理定律形式相同
          - **光速不变原理**：真空中光速在所有惯性系中均为 $ c \\approx 3 \\times 10^8 \\, \\text{m/s} $

          > 提示：该理论导致了时间膨胀、长度收缩等非直观效应，已在粒子加速器和GPS系统中得到实证验证。''',
                'is_active': 1
            }

            # 插入默认提示词
            for prompt_data in [default_system_prompt, default_chitchat_prompt]:
                conn.execute("""
                    INSERT INTO system_prompts (
                        name, display_name, description, prompt_type,
                        role_definition, profile, skills, rules, workflows, output_format, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    prompt_data['name'], prompt_data['display_name'], prompt_data['description'],
                    prompt_data['prompt_type'], prompt_data['role_definition'], prompt_data.get('profile'),
                    prompt_data['skills'], prompt_data['rules'], prompt_data['workflows'],
                    prompt_data.get('output_format'), prompt_data['is_active']
                ))

            conn.commit()
            logger.info("默认系统提示词初始化完成")

    def add_system_prompt(self, name: str, display_name: str, prompt_type: str,
                          role_definition: str, skills: str = None, rules: str = None,
                          workflows: str = None, output_format: str = None,
                          description: str = "", profile: str = None) -> Optional[int]:
        """添加一个新的自定义系统提示词"""
        with self.get_connection() as conn:
            try:
                cursor = conn.execute("""
                    INSERT INTO system_prompts (
                        name, display_name, description, prompt_type,
                        role_definition, profile, skills, rules, workflows, output_format
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (name, display_name, description, prompt_type, role_definition,
                      profile, skills, rules, workflows, output_format))
                logger.info(f"系统提示词 '{name}' 已创建")
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                logger.warning(f"系统提示词名称 '{name}' 已存在")
                return None

    def list_system_prompts(self, prompt_type: str = None) -> List[Dict[str, Any]]:
        """列出所有系统提示词，可按类型过滤"""
        with self.get_connection() as conn:
            if prompt_type:
                cursor = conn.execute("""
                    SELECT * FROM system_prompts WHERE prompt_type = ? ORDER BY prompt_type, created_at
                """, (prompt_type,))
            else:
                cursor = conn.execute("""
                    SELECT * FROM system_prompts ORDER BY prompt_type, created_at
                """)
            return [dict(row) for row in cursor.fetchall()]

    def get_system_prompt_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """根据名称获取系统提示词"""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM system_prompts WHERE name = ?", (name,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_system_prompt(self, name: str, **kwargs) -> bool:
        """更新系统提示词"""
        allowed_fields = {'display_name', 'description', 'role_definition', 'profile',
                          'skills', 'rules', 'workflows', 'output_format', 'is_active'}
        update_fields = {k: v for k, v in kwargs.items() if k in allowed_fields}

        if not update_fields:
            return False

        with self.get_connection() as conn:
            set_clause = ", ".join(f"{k} = ?" for k in update_fields.keys())
            values = list(update_fields.values()) + [datetime.now(), name]
            conn.execute(
                f"UPDATE system_prompts SET {set_clause}, updated_at = ? WHERE name = ?",
                values
            )
            conn.commit()
            logger.info(f"系统提示词 '{name}' 已更新")
            return True

    def delete_system_prompt(self, name: str) -> bool:
        """删除系统提示词（默认提示词不允许删除）"""
        if name in ['default_system', 'default_chitchat']:
            logger.warning(f"默认提示词 '{name}' 不允许删除")
            return False

        with self.get_connection() as conn:
            cursor = conn.execute("DELETE FROM system_prompts WHERE name = ?", (name,))
            if cursor.rowcount > 0:
                conn.commit()
                logger.info(f"系统提示词 '{name}' 已删除")
                return True
            return False

    def get_active_prompt_by_type(self, prompt_type: str) -> Optional[Dict[str, Any]]:
        """获取指定类型的激活提示词"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM system_prompts
                WHERE prompt_type = ? AND is_active = 1
                ORDER BY updated_at DESC
                LIMIT 1
            """, (prompt_type,))
            row = cursor.fetchone()
            return dict(row) if row else None

# 创建一个全局数据库管理器实例
db_manager = DatabaseManager()
