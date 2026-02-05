# 📜 saga/utils/knowledge_base.py

import os
import uuid
import re
import pickle
from typing import List, Dict, Any, Optional, Tuple

# --- 第三方库 ---
import chromadb
from chromadb.errors import NotFoundError
from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownTextSplitter
from rank_bm25 import BM25Okapi
from langdetect import detect, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException

# --- 内部模块 ---
from .config import config
from .logging_config import logger
from .llm_service import llm_service
from .database import db_manager
from .prompt_manager import prompt_manager

# 确保结果可复现
DetectorFactory.seed = 0

def cut_thinking_txt(text: str) -> str:
    """
    使用正则表达式移除</think>前的内容，专门用于处理模型的思考过程。
    """
    if not text: return ""
    
    pattern = r'(.*?)<\/think>'
    result = re.sub(pattern, '', text, flags=re.DOTALL)
    result = re.sub(r'\n+', '\n', result).strip()
    return result

class SmartTextSplitter:
    """
    智能文本分割器，根据文档类型采用不同策略，并携带元数据。

    RAG优化特性：
    1. 文档类型感知：PDF、Markdown、普通文本采用不同策略
    2. 章节结构保留：PDF文档按章节层级分割
    3. 语义感知重叠：在语义边界处分割
    4. 动态块大小：根据文档特征动态调整
    """
    def __init__(self):
        self.chunk_size = config.get('knowledge_base.chunk_size', 1000)
        self.chunk_overlap = config.get('knowledge_base.chunk_overlap', 150)

        # 基础分割器配置
        self.general_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        )
        self.markdown_splitter = MarkdownTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

        # PDF章节识别模式
        self.pdf_chapter_patterns = [
            r'^(第[一二三四五六七八九十百千万0-9]+[章节卷篇部]|Chapter\s+\d+|Part\s+\d+)',
            r'^[一二三四五六七八九十百千万]+[、．\.]\s*\S',  # 中文序号
            r'^\d+\.\s+\S+',  # 数字序号
            r'^[A-Z][A-Z0-9]+\s+\S+',  # 大写字母序号
        ]

    def split_text(self, text: str, doc_type: str, file_metadata: Dict = None) -> List[Dict[str, Any]]:
        """
        根据文件内容和路径智能分割文本，返回包含文本和元数据的字典列表。

        Args:
            text: 待分割文本
            doc_type: 文档类型 (pdf, markdown, general)
            file_metadata: 文件元数据（用于增强分割策略）

        Returns:
            包含 'text' 和 'metadata' 的字典列表
        """
        if not text or not text.strip():
            return []

        # 清理文本
        text = self._clean_text(text)

        if doc_type == "markdown":
            chunks = self._split_markdown(text)
        elif doc_type == "pdf":
            chunks = self._split_pdf_with_chapters(text, file_metadata)
        else:
            chunks = self._split_general(text)

        # 为每个块添加元数据
        chunk_dicts = []
        for i, chunk_text in enumerate(chunks):
            metadata = {
                'chunk_index': i,
                'chunk_type': self._detect_chunk_type(chunk_text),
                'doc_type': doc_type,
                'language': self._detect_language(chunk_text)
            }
            # 合并文件元数据
            if file_metadata:
                metadata.update(file_metadata)

            chunk_dicts.append({
                'text': chunk_text,
                'metadata': metadata
            })

        return chunk_dicts

    def _clean_text(self, text: str) -> str:
        """清理文本：去除过多空白、修复编码问题等"""
        # 去除多余的空白行
        text = re.sub(r'\n{3,}', '\n\n', text)
        # 去除行首行尾空白
        text = '\n'.join(line.strip() for line in text.split('\n'))
        return text.strip()

    def _split_markdown(self, text: str) -> List[str]:
        """
        分割Markdown文本，保留标题层级结构

        优化策略：
        1. 在标题处分割，保留上下文
        2. 确保代码块完整性
        3. 表格不被分割
        """
        # 使用Markdown专用分割器
        raw_chunks = self.markdown_splitter.split_text(text)

        # 后处理：检查并修复被破坏的结构
        chunks = []
        for chunk in raw_chunks:
            # 确保代码块完整（检查```配对）
            if chunk.count('```') % 2 == 1:
                # 代码块不完整，尝试与下一块合并
                continue
            chunks.append(chunk)

        return chunks if chunks else raw_chunks

    def _split_pdf_with_chapters(self, text: str, file_metadata: Dict = None) -> List[str]:
        """
        分割PDF文本，保留章节结构

        优化策略：
        1. 识别章节标题
        2. 在章节边界处优先分割
        3. 动态调整块大小以适应章节长度
        4. 添加章节上下文到每个块
        """
        lines = text.split('\n')
        chapters = self._identify_chapters(lines)

        if not chapters:
            # 没有识别到章节，使用通用分割
            return self.general_splitter.split_text(text)

        chunks = []
        for chapter in chapters:
            chapter_title = chapter['title']
            chapter_content = chapter['content']

            # 根据章节长度动态调整分割策略
            if len(chapter_content) <= self.chunk_size:
                # 短章节，直接作为一个块
                chunk = f"# {chapter_title}\n\n{chapter_content}"
                chunks.append(chunk)
            else:
                # 长章节，进一步分割但保留章节标题
                sub_chunks = self.general_splitter.split_text(chapter_content)
                for i, sub_chunk in enumerate(sub_chunks):
                    # 添加章节上下文
                    context = f"# {chapter_title}"
                    if i > 0:
                        context += f" (续)"
                    chunk = f"{context}\n\n{sub_chunk}"
                    chunks.append(chunk)

        return chunks

    def _identify_chapters(self, lines: List[str]) -> List[Dict[str, Any]]:
        """识别PDF中的章节结构"""
        chapters = []
        current_chapter = {'title': '引言', 'content': '', 'level': 0}

        for line in lines:
            is_chapter = False
            chapter_level = 0

            # 检查是否匹配章节模式
            for i, pattern in enumerate(self.pdf_chapter_patterns):
                if re.match(pattern, line.strip(), re.IGNORECASE | re.MULTILINE):
                    is_chapter = True
                    chapter_level = i + 1
                    break

            if is_chapter:
                # 保存当前章节
                if current_chapter['content'].strip():
                    chapters.append(current_chapter.copy())
                # 开始新章节
                current_chapter = {
                    'title': line.strip(),
                    'content': '',
                    'level': chapter_level
                }
            else:
                current_chapter['content'] += line + '\n'

        # 添加最后一个章节
        if current_chapter['content'].strip():
            chapters.append(current_chapter)

        # 如果没有识别到章节，返回空列表
        if len(chapters) == 1 and chapters[0]['title'] == '引言':
            return []

        return chapters

    def _split_general(self, text: str) -> List[str]:
        """
        分割普通文本，使用语义边界优化

        优化策略：
        1. 优先在段落边界分割
        2. 保留句子完整性
        3. 使用语义感知的重叠
        """
        return self.general_splitter.split_text(text)

    def _detect_chunk_type(self, chunk_text: str) -> str:
        """检测文本块类型（用于后续检索优化）"""
        if re.search(r'```', chunk_text):
            return 'code'
        elif re.search(r'^#+\s', chunk_text, re.MULTILINE):
            return 'heading'
        elif re.search(r'\|.*\|', chunk_text):
            return 'table'
        elif len(chunk_text.split('\n')) > 5:
            return 'paragraph'
        else:
            return 'short'

    def _detect_language(self, text: str) -> str:
        """检测文本语言"""
        try:
            lang = detect(text[:500])  # 只检测前500字符
            return lang
        except LangDetectException:
            return 'unknown'

class KnowledgeBaseManager:
    """知识库管理类，支持多维度向量隔离、混合检索(ChromaDB+BM25)、假设性文档嵌入HyDE、Reranker精排和上下文溯源。"""
    def __init__(self):
        chroma_db_path = config.get('paths.chroma_db')
        self.bm25_indices_path = config.get('paths.bm25_indices')
        os.makedirs(chroma_db_path, exist_ok=True)
        os.makedirs(self.bm25_indices_path, exist_ok=True)
        
        self.client = chromadb.PersistentClient(path=chroma_db_path)
        self.text_splitter = SmartTextSplitter()
        logger.info(f"ChromaDB 客户端已连接到: {chroma_db_path}")
        logger.info(f"BM25 索引将存放在: {self.bm25_indices_path}")
        
        # 添加嵌入维度缓存
        self.embedding_dimensions = {}
        
    def _get_embedding_dimension(self, model_name: str) -> int:
        """获取指定嵌入模型的向量维度 暂时未使用"""
        if model_name in self.embedding_dimensions:
            return self.embedding_dimensions[model_name]
        
        # 常见模型的预设维度
        dimension_map = {
            'text-embedding-v4': 1024,  # 通义千问text-embedding-v4的维度 2,048、1,536、1,024（默认）、768、512、256、128、64
            'deepseek-text-embedding': 1536,
            'qwen3-embedding:0.6b': 1024,  # Ollama模型
            'mxbai-embed-large': 1024,
            'default_internal': 1024,  # 内部服务默认
        }
        
        if model_name in dimension_map:
            self.embedding_dimensions[model_name] = dimension_map[model_name]
        else:
            # 对于未知模型，使用默认值并尝试动态获取
            logger.warning(f"未知嵌入模型 '{model_name}'，使用默认维度1024")
            self.embedding_dimensions[model_name] = 1024
            
            # 尝试动态获取维度（可选）
            try:
                # 发送一个测试文本获取向量维度
                test_embedding = llm_service.get_embedding("test")
                if test_embedding:
                    dimension = len(test_embedding)
                    self.embedding_dimensions[model_name] = dimension
                    logger.info(f"动态检测到模型 '{model_name}' 的维度为: {dimension}")
            except Exception as e:
                logger.warning(f"无法动态检测模型 '{model_name}' 的维度: {e}")
        
        return self.embedding_dimensions[model_name]
        
    def _get_bm25_index_path(self, kb_id: int) -> str:
        """获取特定知识库的BM25索引文件的路径"""
        return os.path.join(self.bm25_indices_path, f"bm25_kb_{kb_id}.pkl")

    def _rebuild_bm25_index(self, kb_id: int):
        """【核心优化】从数据库直接读取文本块，全量重建指定知识库的BM25索引。"""
        logger.info(f"正在为知识库 ID {kb_id} 高效重建 BM25 索引...")
        
        # 1. 从数据库获取所有chunks
        all_chunks_data = db_manager.get_chunks_by_kb_id(kb_id)
        
        if not all_chunks_data:
            index_path = self._get_bm25_index_path(kb_id)
            if os.path.exists(index_path):
                os.remove(index_path)
            logger.info(f"知识库 ID {kb_id} 为空，已清理 BM25 索引。")
            return
        
        corpus_chunks = [item['chunk_text'] for item in all_chunks_data]
        
        # 2. 构建并保存BM25索引
        tokenized_corpus = [doc.split(" ") for doc in corpus_chunks]
        bm25 = BM25Okapi(tokenized_corpus)
        index_path = self._get_bm25_index_path(kb_id)
        with open(index_path, 'wb') as f:
            # 存储bm25对象和原始chunks，用于BM25检索时的内容返回
            pickle.dump({'bm25': bm25, 'corpus': corpus_chunks}, f)
        
        logger.info(f"BM25 索引已为知识库 ID {kb_id} 成功全量重建，包含 {len(corpus_chunks)} 个文本块。")

    def get_or_create_collection(self, name: str) -> chromadb.Collection:
        """获取或创建一个ChromaDB集合"""
        return self.client.get_or_create_collection(name=name)
    
    def _translate_if_needed(self, text: str) -> str:
        """检测文本语言，如果不是中文，则调用LLM进行翻译。"""
        if not text or not text.strip():
            return ""

        # 1. 预处理：移除代码块、URL、Markdown特殊字符，减少干扰
        # 移除Markdown代码块
        processed_text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        # 移除URL
        processed_text = re.sub(r'https?://\S+', '', processed_text)
        # 移除Markdown图片和链接
        processed_text = re.sub(r'!\[.*?\]\(.*?\)|\[.*?\]\(.*?\)', '', processed_text)
        # 移除Markdown标题标记
        processed_text = re.sub(r'#+\s', '', processed_text)
        # 移除HTML标签
        processed_text = re.sub(r'<.*?>', '', processed_text)
        
        # 只取前1000个字符进行检测，提高效率和准确性
        sample_text = processed_text.strip()[:1000]

        if not sample_text:
            logger.info("文本预处理后为空，跳过翻译。")
            return text

        try:
            # 2. 使用 langdetect 进行检测
            language = detect(sample_text)
            # 支持简体(zh-cn)和繁体(zh-tw)
            if language.startswith('zh'):
                logger.info(f"语言检测为 '{language}'，跳过翻译。")
                return text
        except LangDetectException:
            # 如果文本太短或太模糊无法检测，默认不翻译
            logger.warning("无法明确检测文本语言，将使用原文。")
            return text

        logger.info(f"检测到语言为 '{language}'，开始翻译...")
        try:
            translation_prompt = prompt_manager.render('translate_to_chinese.jinja2', text_to_translate=text)
            messages = [{"role": "user", "content": translation_prompt}]
            
            # 使用一个独立的、轻量的llm_service调用
            translated_text, _ = llm_service.chat_completion(messages, topic_id=0, temperature=0.1)  # topic_id 0 for non-session tasks
            
            if translated_text:
                logger.info("文本翻译成功。")
                return cut_thinking_txt(translated_text)
            else:
                logger.warning("翻译返回空内容，将使用原文。")
                return text
        except Exception as e:
            logger.error(f"翻译过程中出错: {e}，将使用原文。", exc_info=True)
            return text

    def add_document(self, file_path: str, kb_id: int, file_id: int):
        """调用统一的llm_service接口来处理文件处理单个文档并将其添加到与当前模型匹配的知识库集合中。"""
        active_embedding_model = llm_service.get_active_embedding_model_name()
        chroma_collection_name = f"kb_{kb_id}_{active_embedding_model}"
        
        logger.info(f"开始添加文档 '{os.path.basename(file_path)}' 到集合 '{chroma_collection_name}'")
        
        try:
            db_manager.update_file_status(file_id, 'processing')
            
            # 1. 调用 llm_service 的统一接口
            extraction_result = llm_service.extract_text_from_file(file_path)
            if not extraction_result or not extraction_result.get("text"):
                raise ValueError("从文件中未能提取到任何文本。")
            
            text = extraction_result["text"]
            
            # translated_text = self._translate_if_needed(text)
            
            doc_type = extraction_result["doc_type"]
            logger.info(f"成功提取文本，文档类型: {doc_type}, 长度: {len(text)} 字符。")

            # 2. 分割文本 使用翻译后的文本进行分割
            chunk_dicts = self.text_splitter.split_text(text, doc_type)
            if not chunk_dicts: raise ValueError("文本分割后未产生任何片段。")

            # SmartTextSplitter 返回字典列表: [{'text': ..., 'metadata': ...}, ...]
            # 提取纯文本列表用于数据库和向量化
            chunk_texts = [chunk['text'] for chunk in chunk_dicts]

            # 将chunk_texts存入数据库
            db_manager.add_chunks_to_file(file_id, chunk_texts)

            # 3. 向量化和存储
            embeddings = llm_service.get_embedding(chunk_texts)
            if not embeddings: raise RuntimeError("获取嵌入向量失败。")

            collection = self.client.get_or_create_collection(chroma_collection_name)
            ids = [str(uuid.uuid4()) for _ in chunk_texts]

            # 合并元数据：基础信息 + SmartTextSplitter 提供的元数据
            base_name = os.path.basename(file_path)
            metadatas = []
            for i, chunk_dict in enumerate(chunk_dicts):
                metadata = {
                    'source': base_name,
                    'file_id': file_id,
                    'chunk_index': i
                }
                # 合并分割器提供的元数据
                if 'metadata' in chunk_dict:
                    metadata.update(chunk_dict['metadata'])
                metadatas.append(metadata)

            collection.add(ids=ids, embeddings=embeddings, documents=chunk_texts, metadatas=metadatas)
            
            # 4. 增量更新BM25索引(从数据库读取，保证一致性)
            self._rebuild_bm25_index(kb_id)

            db_manager.update_file_status(file_id, 'completed', vector_count=len(chunk_texts))
            logger.info(f"成功将 {len(chunk_texts)} 个向量存入集合 '{chroma_collection_name}'。")

        except Exception as e:
            logger.error(f"添加文档 '{file_path}' 失败: {e}", exc_info=True)
            db_manager.update_file_status(file_id, 'failed')
            # 如果过程中断，最好也重建一次BM25索引以保证一致性
            self._rebuild_bm25_index(kb_id)
            
    def delete_document(self, kb_id: int, file_id: int, embedding_model: str):
        """根据 file_id 从指定的 ChromaDB 集合和 BM25 索引中删除所有相关的向量。"""
        chroma_collection_name = f"kb_{kb_id}_{embedding_model}"
        logger.info(f"准备从集合 '{chroma_collection_name}' 中删除 file_id 为 {file_id} 的所有向量。")
        try:
            collection = self.client.get_collection(name=chroma_collection_name)
            # 使用 where filter 进行精确删除
            collection.delete(where={"file_id": file_id})
            logger.info(f"成功从集合 '{chroma_collection_name}' 中删除与 file_id {file_id} 相关的所有向量。")

        except NotFoundError:
            # 集合不存在（例如文档上传失败时未创建），这是正常情况
            logger.info(f"ChromaDB 集合 '{chroma_collection_name}' 不存在，无需删除向量。")
        except Exception as e:
            # 其他异常，记录错误但不让程序崩溃
            logger.error(f"从 ChromaDB 删除文档向量失败: {e}", exc_info=True)

        # 触发BM25索引的全量重建，以确保清理干净
        # 数据库的ON DELETE CASCADE会自动删除knowledge_files和file_chunks中的记录
        self._rebuild_bm25_index(kb_id)
        logger.info(f"已触发知识库ID {kb_id} 的BM25索引全量重建。")
        
        
    def _reciprocal_rank_fusion(self, search_results_list: List[List[Dict]], k=60) -> List[Dict]:
        """对多路搜索结果进行RRF合并"""
        fused_scores = {}
        for results in search_results_list:
            for rank, result in enumerate(results):
                doc_content = result.get('content')
                if not isinstance(doc_content, str):
                    continue    # 如果内容不是字符串，则跳过此结果
                if doc_content not in fused_scores:
                    fused_scores[doc_content] = {'score': 0, 'doc': result}
                fused_scores[doc_content]['score'] += 1 / (rank + k)
        
        reranked_results = sorted(fused_scores.values(), key=lambda x: x['score'], reverse=True)
        return [item['doc'] for item in reranked_results]

    def search(self, query: str, kb_ids: List[int]) -> List[Dict[str, Any]]:
        """在与当前模型匹配的知识库中进行语义搜索，执行混合检索、HyDE、Rerank，并返回用于溯源的结果。"""
        if not kb_ids: return []
        
        top_k = config.get('knowledge_base.top_k', 10)
        rerank_top_n = config.get('knowledge_base.rerank_top_n', 3)
        relevance_threshold = config.get('knowledge_base.relevance_threshold', 1.2)
        
        final_query = query
        
        # 假设性文档嵌入（Hypothetical Document Embeddings，简称 HyDE）是一种用于提升信息检索系统，特别是检索增强生成（RAG）流程效果的高级技术。其核心思想非常巧妙：不直接使用用户的原始问题进行检索，而是先让大语言模型（LLM）根据该问题生成一个“假设性”的答案文档，然后利用这个假设文档去检索与之最相关的真实文档。
        # --- 1. HyDE (如果启用) ---
        if config.get('knowledge_base.enable_hyde', False):
            try:
                hyde_prompt = prompt_manager.render('hyde_generation.jinja2', user_query=query)
                hypothetical_answer, _ = llm_service.chat_completion([{"role": "user", "content": hyde_prompt}], topic_id=0, temperature=0.7)
                if hypothetical_answer:
                    final_query = cut_thinking_txt(hypothetical_answer)
                    logger.info(f"HyDE 已启用，使用假设性文档进行搜索。")
            except Exception as e:
                logger.warning(f"HyDE 生成失败: {e}，将使用原始查询。")
                
        # --- 2. 混合检索 ---
        all_search_results = []
        
        # 2.1 向量检索 (Vector Search)
        try:
            active_embedding_model = llm_service.get_active_embedding_model_name()
            query_embedding = llm_service.get_embedding(final_query)
            if query_embedding:
                vector_results = []
                for kb_id in kb_ids:
                    collection_name = f"kb_{kb_id}_{active_embedding_model}"
                    try:
                        collection = self.client.get_collection(name=collection_name)
                        results = collection.query(query_embeddings=[query_embedding], n_results=top_k)
                        if results and results['ids'][0]:
                            for i in range(len(results['ids'][0])):
                                distance = results['distances'][0][i]
                                if distance < relevance_threshold:
                                    vector_results.append({
                                        "content": results['documents'][0][i],
                                        "metadata": results['metadatas'][0][i],
                                        "distance": distance
                                    })
                                else:
                                    # 记录被过滤掉的文档，用于调试
                                    logger.debug(f"Vector search result filtered out by threshold. Distance: {distance:.4f} > {relevance_threshold}. Content: {results['documents'][0][i][:100]}...")
                    except Exception:
                        continue
                if vector_results:
                    all_search_results.append(vector_results)
        except Exception as e:
            logger.error(f"向量搜索失败: {e}", exc_info=True)
            
        # 2.2 关键词检索 (BM25 Search)
        bm25_results = []
        for kb_id in kb_ids:
            index_path = self._get_bm25_index_path(kb_id)
            if os.path.exists(index_path):
                with open(index_path, 'rb') as f:
                    data = pickle.load(f)
                    bm25 = data['bm25']
                    corpus = data['corpus']
                
                tokenized_query = query.split(" ")
                doc_scores = bm25.get_scores(tokenized_query)
                
                # 获取分数最高的 top_k 个结果
                top_indices = sorted(range(len(doc_scores)), key=lambda i: doc_scores[i], reverse=True)[:top_k]
                for i in top_indices:
                    score = doc_scores[i]
                    if score > 0:
                        bm25_results.append({"content": corpus[i], "metadata": {"source": "BM25 Keyword Search"}, "score": score})
                    else:
                        logger.debug(f"BM25 result filtered out by score <= 0. Score: {score:.4f}.")
        if bm25_results:
            all_search_results.append(bm25_results)

        if not all_search_results:
            logger.info("混合检索在所有知识库中均未找到相关结果。")
            return []
        
        # --- 3. 结果融合 (RRF) ---
        fused_results = self._reciprocal_rank_fusion(all_search_results)
        
        # --- 4. Reranker 精排 ---
        documents_to_rerank = [res['content'] for res in fused_results]
        reranked_indices = llm_service.rerank(query, documents_to_rerank)
        final_results = [fused_results[i] for i in reranked_indices][:rerank_top_n]

        # --- 5. 格式化输出以支持溯源 ---
        for i, res in enumerate(final_results):
            res['citation_id'] = f"来源-{i+1}"
        
        logger.info(f"搜索完成，混合检索共找到 {len(fused_results)} 条，Rerank后返回前 {len(final_results)} 条。")
        return final_results

# 创建一个全局实例
kb_manager = KnowledgeBaseManager()
