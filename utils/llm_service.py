# 📜 saga/utils/llm_service.py

import requests
import os
import io
import re
import json
from pathlib import Path
from datetime import datetime
from openai import OpenAI, APIError
from typing import List, Dict, Any, Union, Optional, Callable, Tuple, Generator

# --- 内部模块导入 ---
from .config import config
from .logging_config import logger
from .database import db_manager
from .prompt_manager import prompt_manager

# --- 第三方库导入 ---
try:
    import tiktoken
    TOKENIZER = tiktoken.get_encoding("cl100k_base")
except ImportError:
    logger.error("tiktoken 库未安装。请运行 'pip install tiktoken'")
    TOKENIZER = None

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None
    
try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import easyocr
    # 首次运行时会自动下载模型，可能会比较慢
    EASYOCR_READER = easyocr.Reader(['ch_sim', 'en']) 
except ImportError:
    easyocr = None
    EASYOCR_READER = None
    
# MinerU 高质量文档解析服务
try:
    from mineru.cli.common import do_parse
    from mineru.utils.enum_class import MakeMode
    MINERU_AVAILABLE = True
except ImportError:
    do_parse = None
    MakeMode = None
    MINERU_AVAILABLE = False
    logger.warning("MinerU 未安装，将使用备用 OCR 服务")

# Monkey patch 跳过模型检查（如果 MinerU 可用）
if MINERU_AVAILABLE:
    try:
        from mineru_vl_utils.vlm_client import http_client
        original_check = http_client.HttpVlmClient._check_model_name
        def noop_check(self, base_url, model_name):
            logger.debug(f"[MinerU] Skipping model check, using model: {model_name}")
        http_client.HttpVlmClient._check_model_name = noop_check
    except ImportError:
        logger.debug("MinerU VLM client not available, skipping monkey patch")

def count_tokens(text: str) -> int:
    """使用tiktoken计算文本的token数量。如果库不存在，则进行估算。"""
    if not text:
        return 0
    if TOKENIZER:
        return len(TOKENIZER.encode(text))
    else:
        # 估算：平均一个token约等于4个字符
        return len(text) // 4
    
def cut_thinking_txt(text: str) -> str:
    """
    使用正则表达式移除</think>前的内容，专门用于处理模型的思考过程。
    """
    if not text: return ""
    
    pattern = r'(.*?)<\/think>'
    result = re.sub(pattern, '', text, flags=re.DOTALL)
    result = re.sub(r'\n+', '\n', result).strip()
    return result

class LLMService:
    """
    LLM服务类，采用自刷新单例模式，能够动态响应运行时的配置变更，并统一负责所有文件文本提取。
    """
    _instance = None

    # 使用 __new__ 来实现单例模式
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(LLMService, cls).__new__(cls, *args, **kwargs)
            # 首次创建时执行初始化
            cls._instance._initialize_services()
        return cls._instance

    def _initialize_services(self):
        """封装了完整的初始化和绑定逻辑。"""
        self.mode = config.active_llm_mode
        self.service_config = config.get_llm_config()
        self.conversation_config = config.get('conversation')
        
        self.chat_provider: Optional[Callable] = None
        self.embedding_provider: Optional[Callable] = None
        self.rerank_provider: Optional[Callable] = None
        
        self._init_clients()
        self._bind_providers()
        
        logger.info(f"LLM服务已初始化/刷新，当前生效模式: '{self.mode}'")

    def _check_and_refresh_config(self):
        """
        在每次外部调用时检查配置。如果模式已更改，则完全重新初始化服务。
        """
        current_config_mode = config.active_llm_mode
        if self.mode != current_config_mode:
            logger.warning(f"检测到服务模式已从 '{self.mode}' 切换到 '{current_config_mode}'。正在重新加载所有服务...")
            # 重新执行完整的初始化流程
            self._initialize_services()
            logger.info("LLM 服务已成功切换到新模式。")

    def _init_clients(self):
        """根据当前模式初始化所有可能的API客户端"""
        if self.mode == 'external':
            # 新配置结构：按服务类型分组 (chat/embedding/reranker/ocr)
            # 每个服务类型下有多个提供商
            service_types = ['chat', 'embedding', 'reranker', 'ocr']

            for service_type in service_types:
                service_config = self.service_config.get(service_type, {})

                # 获取所有提供商配置
                for provider_name, provider_config in service_config.items():
                    if provider_name == 'active_provider':
                        continue

                    api_key = provider_config.get('api_key', '')
                    base_url = provider_config.get('base_url', '')

                    # 跳过未配置或占位符API密钥
                    if not api_key or api_key.startswith('sk-your-') or api_key.startswith('your-'):
                        continue

                    # 避免重复初始化同一个提供商的客户端
                    client_attr = f'{provider_name}_client'
                    if not hasattr(self, client_attr):
                        try:
                            client = OpenAI(api_key=api_key, base_url=base_url)
                            setattr(self, client_attr, client)
                            logger.info(f"{provider_name} 客户端初始化成功 ({service_type})")
                        except Exception as e:
                            logger.error(f"初始化 {provider_name} 客户端失败 ({service_type}): {e}")
                            setattr(self, client_attr, None)

        # internal 和 local 模式的客户端在各自的方法中按需创建，无需预初始化

    def _bind_providers(self):
        """【核心】根据当前模式，将具体实现绑定到统一的服务接口上。"""
        if self.mode == 'internal':
            self.chat_provider = self._internal_chat_completion
            self.embedding_provider = self._internal_get_embedding
            if self.service_config.get('reranker', {}).get('url'):
                self.rerank_provider = self._internal_rerank

        elif self.mode == 'external':
            # 检查是否有任何可用的客户端
            has_valid_client = any(
                hasattr(self, f'{provider}_client') and getattr(self, f'{provider}_client') is not None
                for provider in ['qwen', 'deepseek', 'openai', 'anthropic', 'google', 'glm']
            )

            if not has_valid_client:
                # 不再自动降级，而是记录错误并设置提供者为None
                error_msg = "外部API未配置或无效。请在系统设置页面配置至少一个提供商的API密钥。"
                logger.error(error_msg)
                # 将所有提供商设置为None，以便后续调用时抛出明确的错误
                self.chat_provider = None
                self.embedding_provider = None
                self.rerank_provider = None
                return

            self.chat_provider = self._external_chat_completion
            self.embedding_provider = self._external_get_embedding
            self.rerank_provider = self._external_rerank

        elif self.mode == 'local':
            self.chat_provider = self._local_chat_completion
            self.embedding_provider = self._local_get_embedding
            if self.service_config.get('reranker_model'):
                self.rerank_provider = self._local_rerank
            
    # --- 公共接口方法 (Public Interface Methods) ---
    # 【重要】所有公共方法都必须在开头调用 self._check_and_refresh_config()
    
    def extract_text_from_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        统一的文件文本提取接口，根据当前模式执行正确的策略。
        返回一个包含 'text' 和 'doc_type' 的字典，或在失败时返回 None。
        """
        self._check_and_refresh_config() # 确保使用最新的模式

        file_ext = os.path.splitext(file_path)[1].lower()
        doc_type = "markdown" if file_ext == '.md' else "general"

        try:
            if self.mode == 'internal':
                # internal 模式：只使用内部OCR，失败则失败，不降级
                if file_ext in ['.pdf', '.png', '.jpg', '.jpeg']:
                    logger.info(f"Internal模式: 正在为 '{file_path}' 调用内部OCR服务...")
                    return self._internal_ocr(file_path)
                elif file_ext in ['.txt', '.md']:
                    logger.info(f"Internal模式: 正在为 '{file_path}' 执行本地文本文件解析...")
                    return self._local_extraction(file_path, doc_type)
                else:
                    logger.warning(f"Internal模式: 不支持的文件类型 '{file_ext}'，无法解析。")
                    return None
            
            elif self.mode == 'external':
                # external 模式：只使用外部OCR，失败则失败，不降级
                logger.info(f"External模式: 正在为 '{file_path}' 调用外部OCR服务...")
            
                return self._external_ocr(file_path)

            elif self.mode == 'local':
                # local 模式：优先使用 Ollama 多模态 OCR，失败则使用本地解析
                if file_ext in ['.pdf', '.png', '.jpg', '.jpeg']:
                    logger.info(f"Local模式: 正在为 '{file_path}' 调用 Ollama OCR 服务...")
                    result = self._local_ollama_ocr(file_path)
                    if result:
                        return result
                    # OCR 失败，降级到本地解析
                    logger.info(f"Ollama OCR 失败，尝试本地解析...")
                    return self._local_extraction(file_path, doc_type)
                elif file_ext in ['.txt', '.md']:
                    logger.info(f"Local模式: 正在为 '{file_path}' 执行本地文本文件解析...")
                    return self._local_extraction(file_path, doc_type)
                else:
                    logger.warning(f"Local模式: 不支持的文件类型 '{file_ext}'，无法解析。")
                    return None

        except Exception as e:
            logger.error(f"在 '{self.mode}' 模式下提取文件 '{file_path}' 文本失败: {e}", exc_info=True)
            return None

    # --- 各种模式的私有实现 ---
    def _mineru_parse(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        使用 MinerU 高质量文档解析服务解析 PDF 文档。

        MinerU 优势：
        - 支持数学公式识别（LaTeX 格式）
        - 支持复杂表格结构
        - 支持多列布局
        - 支持图片和图表描述
        - 输出结构化 Markdown 格式

        注意：
        - 仅支持 PDF 文件
        - 仅在企业内网（internal）模式下可用
        - 大文档处理时间较长，请耐心等待
        - 结果保存在 output_dir 目录下
        """
        # MinerU 仅在企业内网模式下可用
        if self.mode != 'internal':
            logger.debug(f"MinerU 仅在企业内网模式下可用，当前模式: {self.mode}")
            return None

        if not MINERU_AVAILABLE:
            logger.debug("MinerU 不可用（未安装 mineru 包），跳过")
            return None

        mineru_config = self.service_config.get('mineru', {})
        if not mineru_config.get('enabled'):
            logger.debug("MinerU 配置中未启用，跳过")
            return None

        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext != '.pdf':
            logger.debug(f"MinerU 仅支持 PDF 文件，当前文件类型: {file_ext}")
            return None

        server_url = mineru_config.get('server_url')
        model_name = mineru_config.get('model_name')
        output_dir = mineru_config.get('output_dir', 'data/mineru_output/')

        if not server_url or not model_name:
            logger.error("MinerU 配置不完整，缺少 server_url 或 model_name")
            return None

        try:
            # 确保输出目录存在
            Path(output_dir).mkdir(parents=True, exist_ok=True)

            # 设置环境变量
            os.environ['MINERU_VL_MODEL_NAME'] = model_name

            # 读取 PDF 文件
            with open(file_path, "rb") as f:
                pdf_bytes = f.read()
                file_size_mb = len(pdf_bytes) / (1024 * 1024)

            logger.info(f"使用 MinerU 解析 PDF: {os.path.basename(file_path)} ({file_size_mb:.2f} MB)")
            logger.info("MinerU 解析可能需要较长时间，请耐心等待...")

            # 调用 MinerU 解析
            do_parse(
                output_dir=output_dir,
                pdf_file_names=[Path(file_path).name],
                pdf_bytes_list=[pdf_bytes],
                p_lang_list=["ch"],  # 中文
                backend="vlm-http-client",
                parse_method="auto",
                formula_enable=True,   # 启用公式识别
                table_enable=True,     # 启用表格识别
                server_url=server_url,
                f_dump_md=True,
                f_dump_middle_json=True,
                f_dump_content_list=True,
                f_make_md_mode=MakeMode.MM_MD
            )

            # 读取解析结果（markdown 格式）
            # MinerU 使用完整文件名（含.pdf扩展名）创建目录，并在 vlm 子目录中输出
            result_dir = Path(output_dir) / Path(file_path).name / "vlm"
            # MinerU 输出的 markdown 文件名为: 原文件名.pdf.md
            md_file = result_dir / f"{Path(file_path).name}.md"

            if md_file.exists():
                with open(md_file, 'r', encoding='utf-8') as f:
                    extracted_text = f.read()

                logger.info(f"MinerU 解析成功: {os.path.basename(file_path)}，提取文本长度: {len(extracted_text)} 字符")
                return {
                    "text": extracted_text,
                    "doc_type": "mineru_processed",
                    "metadata": {
                        "parser": "MinerU",
                        "server_url": server_url,
                        "model": model_name,
                        "output_file": str(md_file)
                    }
                }
            else:
                logger.error(f"MinerU 解析完成，但未找到输出文件: {md_file}，期望目录: {result_dir}")
                return None

        except Exception as e:
            logger.error(f"MinerU 解析失败: {e}", exc_info=True)
            return None
            
    def _internal_ocr(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        调用内部OCR服务，处理PDF和图片文件。

        处理策略：
        - PDF 文件：优先使用 MinerU 高质量解析（支持公式、表格、多列布局）
          失败时降级到普通 OCR 服务，支持分块处理大文档
        - 图片文件（PNG/JPG/JPEG）：使用普通 OCR 服务
          支持自动缩放处理高清长图片
        """
        file_ext = os.path.splitext(file_path)[1].lower()
        file_type = 'pdf' if file_ext == '.pdf' else 'image'

        # ========== PDF 文件处理 ==========
        # 优先尝试使用 MinerU 高质量解析（支持公式、表格、多列布局等复杂内容）
        if file_ext == '.pdf':
            logger.info("检测到 PDF 文件，优先尝试使用 MinerU 解析...")
            mineru_result = self._mineru_parse(file_path)
            if mineru_result:
                logger.info("MinerU 解析成功！")
                return mineru_result
            else:
                logger.info("MinerU 解析失败或不可用，降级到普通 OCR 服务...")

        # ========== 降级：使用普通 OCR 服务 ==========
        url = self.service_config.get('ocr', {}).get(f'{file_type}_url')

        if not url:
            logger.error(f"Internal模式下未配置 '{file_type}' 的OCR URL。")
            return None

        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f)}
            try:
                response = requests.post(url, files=files, timeout=600)
                response.raise_for_status()
                api_result = response.json()

                # 兼容不同OCR服务可能返回的格式
                if file_type == 'pdf':
                    text = api_result.get("result", {}).get("full_text", "")
                else: # image
                    text = api_result.get("result", {}).get("text", "")

                logger.info(f"完成从 '{file_path}' 提取有效文本")

                return {"text": text, "doc_type": "ocr_processed"}
            except requests.RequestException as e:
                logger.error(f"内部OCR请求失败: {e}")
                # 大文档降级处理
                if file_ext == '.pdf':
                    return self._process_large_pdf(file_path, url)
                # 高清长图片降级处理
                elif file_ext in ['.png', '.jpg', '.jpeg']:
                    return self._handle_image_ocr(file_path, url)
                else:
                    return None
            
    def _process_large_pdf(self, file_path: str, url: str) -> Optional[Dict[str, Any]]:
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext == '.pdf':
            file_basename = os.path.basename(file_path)
            logger.warning(f"PDF '{os.path.basename(file_path)}' 按 5 页/块的分块处理模式。")
            all_texts = []
            try:
                with open(file_path, 'rb') as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    num_pages = len(pdf_reader.pages)
                    
                    # 迭代分块
                    for i in range(0, num_pages, 5):
                        chunk_start = i
                        chunk_end = min(i + 5, num_pages)
                        
                        pdf_writer = PyPDF2.PdfWriter()
                        for page_num in range(chunk_start, chunk_end):
                            pdf_writer.add_page(pdf_reader.pages[page_num])
                        
                        page_buffer = io.BytesIO()
                        pdf_writer.write(page_buffer)
                        page_buffer.seek(0)

                        logger.info(f"正在发送PDF块 (页码 {chunk_start + 1}-{chunk_end})...")
                        
                        chunk_filename = f"{os.path.splitext(file_basename)[0]}_pages_{chunk_start+1}-{chunk_end}.pdf"
                        files = {'file': (chunk_filename, page_buffer, 'application/pdf')}
                        
                        try:
                            # 为每个块设置一个较短的超时
                            chunk_response = requests.post(url, files=files, timeout=600)
                            chunk_response.raise_for_status()
                            api_result = chunk_response.json()
                            text = api_result.get("result", {}).get("full_text", "")
                            if text:
                                all_texts.append(text)
                            logger.info(f"PDF块 (页码 {chunk_start + 1}-{chunk_end}) 处理成功。")
                        except Exception as chunk_e:
                            logger.error(f"处理PDF块 (页码 {chunk_start + 1}-{chunk_end}) 时发生错误: {chunk_e}")
                            continue # 跳过失败的块

                final_text = "\n\n--- Chunk Break ---\n\n".join(all_texts)
                logger.info(f"PDF '{file_basename}' 已通过分块模式处理完成。")
                return {"text": final_text, "doc_type": "ocr_processed"}

            except Exception as fallback_e:
                logger.error(f"在分块降级处理模式下发生严重错误: {fallback_e}", exc_info=True)
                return None
            
    def _handle_image_ocr(self, file_path: str, url: str) -> Optional[Dict[str, Any]]:
        """
        处理高清长图片的 OCR 识别。

        策略：
        1. 检查图片尺寸，超过 4096px 自动等比缩放
        2. 转换 RGBA 为 RGB 格式
        3. 使用 JPEG 格式传输以减少带宽
        4. 失败时返回 None
        """
        image_url = url
        if not image_url: return None
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in ['.png', '.jpg', '.jpeg']:
            return None

        file_basename = os.path.basename(file_path)
        MAX_DIMENSION = 4096  # OCR 服务支持的最大尺寸

        try:
            with Image.open(file_path) as img:
                original_size = img.size
                logger.info(f"图片尺寸: {original_size[0]}x{original_size[1]}")

                # 如果图片超过最大尺寸，等比缩放
                if img.size[0] > MAX_DIMENSION or img.size[1] > MAX_DIMENSION:
                    logger.info(f"图片尺寸超过 {MAX_DIMENSION}px，执行等比缩放...")
                    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
                    logger.info(f"缩放后尺寸: {img.size[0]}x{img.size[1]}")

                # 转换格式：RGBA -> RGB
                img_buffer = io.BytesIO()
                if img.mode == 'RGBA' or 'transparency' in img.info:
                    img = img.convert('RGB')
                img.save(img_buffer, format='JPEG', quality=95)
                img_buffer.seek(0)

                logger.info(f"发送图片到 OCR 服务，缓冲区大小: {img_buffer.tell() / 1024:.1f} KB")

            files = {'file': (file_basename, img_buffer, 'image/jpeg')}
            response = requests.post(image_url, files=files, timeout=600)
            response.raise_for_status()
            text = response.json().get("result", {}).get("text", "")

            if text:
                logger.info(f"图片 OCR 成功，提取文本长度: {len(text)} 字符")
                return {"text": text, "doc_type": "ocr_processed"}
            else:
                logger.warning("图片 OCR 返回空文本")
                return None

        except Exception as e:
            logger.error(f"处理图片 '{file_basename}' 时出错: {e}", exc_info=True)
            return None
            
    def _external_ocr(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        外部API OCR文本提取 - 支持优先级降级

        优先使用 slot_1，失败则尝试 slot_2
        记录 parse_source 和 parse_warning
        """
        # 获取所有启用的OCR槽位，按优先级排序
        enabled_slots = config.get_enabled_slots('ocr')

        if not enabled_slots:
            logger.warning("未配置启用的OCR槽位")
            return None

        # 按优先级尝试每个槽位
        for slot_num in enabled_slots:
            slot_config = config.get_slot_config('ocr', slot_num)
            provider = slot_config.get('provider', '')
            model = slot_config.get('model_name', '')
            base_url = slot_config.get('base_url', '')
            api_key = slot_config.get('api_key', '')

            if not provider or not model or not base_url:
                logger.warning(f"槽位 {slot_num} 配置不完整，跳过")
                continue

            logger.info(f"尝试使用槽位 {slot_num} ({provider}/{model}) 处理文件: {file_path}")

            result = self._ocr_with_slot(file_path, provider, model, base_url, api_key, slot_num)

            if result:
                # 成功解析
                result['parse_source'] = f'slot_{slot_num}'
                if slot_num != enabled_slots[0]:
                    # 如果使用的是备用槽位，添加警告
                    result['parse_warning'] = f"主槽位 (slot_{enabled_slots[0]}) 解析失败，已自动切换到备用槽位 (slot_{slot_num})"
                return result
            else:
                logger.warning(f"槽位 {slot_num} 解析失败，尝试下一个槽位")

        # 所有槽位都失败
        logger.error("所有OCR槽位均解析失败")
        return None

    def _ocr_with_slot(self, file_path: str, provider: str, model: str, base_url: str, api_key: str, slot_num: int) -> Optional[Dict[str, Any]]:
        """
        使用指定槽位进行OCR解析

        Args:
            file_path: 文件路径
            provider: 提供商名称
            model: 模型名称
            base_url: Base URL
            api_key: API密钥
            slot_num: 槽位编号

        Returns:
            解析结果字典，失败返回None
        """
        try:
            if provider == 'qwen':
                return self._qwen_ocr(file_path, model, api_key)
            elif provider in ['deepseek', 'openai', 'anthropic', 'google', 'glm']:
                return self._vision_ocr(file_path, provider, model, api_key)
            else:
                logger.warning(f"提供商 {provider} 暂不支持OCR")
                return None

        except Exception as e:
            logger.error(f"槽位 {slot_num} ({provider}/{model}) OCR失败: {e}")
            return None

    def _qwen_ocr(self, file_path: str, model: str, api_key: str) -> Optional[Dict[str, Any]]:
        """使用通义千问进行OCR（支持长文档）"""
        try:
            # 创建临时客户端
            client = OpenAI(api_key=api_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")

            from pathlib import Path
            file_obj = client.files.create(
                file=Path(file_path),
                purpose="file-extract"
            )

            logger.info(f"文件上传成功，文件ID: {file_obj.id}")

            parser_prompt = prompt_manager.render('doc_parser_prompt.jinja2')
            messages = [
                {'role': 'system', 'content': parser_prompt},
                {'role': 'system', 'content': f'fileid://{file_obj.id}'},
                {'role': 'user', 'content': '请提取文档中的所有内容，精准的中文输出'}
            ]

            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
                max_tokens=32768,
                stream=False
            )

            extracted_text = completion.choices[0].message.content

            if hasattr(completion, 'usage'):
                usage = completion.usage
                logger.info(f"OCR提取消耗token: 输入={usage.prompt_tokens}, 输出={usage.completion_tokens}, 总计={usage.total_tokens}")

            if extracted_text:
                return {
                    "text": extracted_text,
                    "doc_type": "ocr_processed",
                    "metadata": {
                        "model": model,
                        "file_id": file_obj.id,
                        "file_type": os.path.splitext(file_path)[1],
                        "token_usage": completion.usage.model_dump() if hasattr(completion, 'usage') else None
                    }
                }
            else:
                logger.warning("OCR提取返回空文本")
                return None

        except Exception as e:
            logger.error(f"通义千问OCR失败: {e}")
            return None

    def _vision_ocr(self, file_path: str, provider: str, model: str, api_key: str) -> Optional[Dict[str, Any]]:
        """使用视觉模型进行OCR（适用于图片）"""
        try:
            # 检查文件类型
            file_ext = os.path.splitext(file_path)[1].lower()
            if file_ext not in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
                logger.warning(f"视觉模型OCR仅支持图片文件，当前文件: {file_ext}")
                return None

            # 读取图片并转换为base64
            import base64
            with open(file_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            # 构建请求
            client = OpenAI(api_key=api_key)

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请提取图片中的所有文字内容，保持原有格式和结构。"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_data}"
                            }
                        }
                    ]
                }
            ]

            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
                max_tokens=4096
            )

            extracted_text = completion.choices[0].message.content

            if extracted_text:
                return {
                    "text": extracted_text,
                    "doc_type": "ocr_image",
                    "metadata": {
                        "model": model,
                        "file_type": file_ext,
                        "token_usage": completion.usage.model_dump() if hasattr(completion, 'usage') else None
                    }
                }
            else:
                logger.warning("视觉模型OCR返回空文本")
                return None

        except Exception as e:
            logger.error(f"{provider} 视觉模型OCR失败: {e}")
            return None

    def _local_ollama_ocr(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        使用本地 Ollama 多模态模型进行 OCR。

        支持 PDF 和图片文件，使用配置的多模态模型（如 qwen3-vl:2b）。
        """
        local_config = self.service_config
        ocr_model = local_config.get('ocr_model', '')
        host = local_config.get('host', 'http://localhost:11434')

        if not ocr_model:
            logger.warning("本地 Ollama 未配置 OCR 模型")
            return None

        file_ext = os.path.splitext(file_path)[1].lower()

        try:
            # 对于 PDF，需要先转换为图片
            if file_ext == '.pdf':
                # 检查是否安装了 pdf2image
                try:
                    from pdf2image import convert_from_path
                    # 将 PDF 第一页转换为图片
                    images = convert_from_path(file_path, first_page=1, last_page=1)
                    if not images:
                        logger.error(f"PDF 转换图片失败: {file_path}")
                        return None
                    # 保存临时图片
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                        images[0].save(tmp.name, 'PNG')
                        image_path = tmp.name
                except ImportError:
                    logger.warning("未安装 pdf2image，无法处理 PDF 文件")
                    return None
                except Exception as e:
                    logger.error(f"PDF 转图片失败: {e}")
                    return None
            else:
                image_path = file_path

            # 读取图片并编码为 base64
            import base64
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            # 构建 Ollama API 请求
            import requests
            api_url = f"{host}/api/chat"

            payload = {
                "model": ocr_model,
                "stream": False,
                "messages": [
                    {
                        "role": "user",
                        "content": "请识别这张图片中的所有文字内容，包括表格、公式等。请完整地输出识别到的文字，保持原有的格式和结构。"
                    }
                ],
                "images": [image_data]
            }

            response = requests.post(api_url, json=payload, timeout=120)
            response.raise_for_status()
            result = response.json()

            if result and 'message' in result and 'content' in result['message']:
                text = result['message']['content'].strip()
                logger.info(f"Ollama OCR 成功识别文本，长度: {len(text)} 字符")

                # 清理临时文件
                if file_ext == '.pdf' and image_path != file_path:
                    try:
                        os.unlink(image_path)
                    except:
                        pass

                return {
                    "text": text,
                    "doc_type": "ocr_processed",
                    "metadata": {
                        "model": ocr_model,
                        "file_type": file_ext,
                        "source": "local_ollama"
                    }
                }
            else:
                logger.warning("Ollama OCR 返回空文本")
                return None

        except Exception as e:
            logger.error(f"Ollama OCR 失败: {e}")
            return None

    def _local_extraction(self, file_path: str, doc_type: str) -> Optional[Dict[str, Any]]:
        """
        本地文件解析的集合。它会尝试多种库来提取文本。
        """
        file_ext = os.path.splitext(file_path)[1].lower()
        text = ""

        if file_ext == '.pdf':
            # 策略1：优先使用 pdfplumber
            if pdfplumber:
                try:
                    with pdfplumber.open(file_path) as pdf:
                        text = "\n".join(page.extract_text() for page in pdf.pages if page.extract_text())
                    logger.info(f"使用 pdfplumber 成功提取PDF: {os.path.basename(file_path)}")
                except Exception as e:
                    logger.warning(f"pdfplumber 提取失败 ({e})，尝试其他方法...")
                    text = ""

            # 策略2：如果 pdfplumber 失败或未安装，或提取文本过少，使用 PyPDF2
            if not text and PyPDF2:
                try:
                    with open(file_path, 'rb') as f:
                        reader = PyPDF2.PdfReader(f)
                        text = "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
                    logger.info(f"使用 PyPDF2 成功提取PDF: {os.path.basename(file_path)}")
                except Exception as e:
                    logger.warning(f"PyPDF2 提取失败 ({e})...")
                    text = ""
        
        elif file_ext in ['.png', '.jpg', '.jpeg']:
            if EASYOCR_READER:
                try:
                    result = EASYOCR_READER.readtext(file_path, detail=0, paragraph=True)
                    text = "\n".join(result)
                    logger.info(f"使用 easyocr 成功识别图片: {os.path.basename(file_path)}")
                except Exception as e:
                    logger.error(f"easyocr 识别失败: {e}")
            else:
                logger.warning("easyocr 未安装，无法识别图片。")

        elif file_ext in ['.txt', '.md']:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        
        
        if text:
            logger.info(f"完成从 '{file_path}' 提取有效文本")
            
            return {"text": text, "doc_type": doc_type}
        else:
            logger.error(f"所有本地方法均未能从 '{file_path}' 提取出有效文本。")
            return None

    def get_active_embedding_model_name(self) -> str:
        """
        获取当前激活的 embedding 模型的安全名称，用于构建 collection 名称。

        支持新的 slot-based 配置：
        - 获取激活的 embedding 槽位
        - 使用槽位的 provider 和 model_name 构建唯一标识
        """
        self._check_and_refresh_config()

        if self.mode == 'internal':
            model = self.service_config.get('embedding', {}).get('model', 'default_internal')
        elif self.mode == 'local':
            model = self.service_config.get('embedding_model', 'default_local')
        elif self.mode == 'external':
            # 使用新的 slot-based 配置获取激活的 embedding 槽位
            active_slot = config.get_active_embedding_slot()
            if active_slot:
                slot_config = config.get_slot_config('embedding', active_slot)
                provider = slot_config.get('provider', '')
                model_name = slot_config.get('model_name', 'default_external')
                # 添加提供商前缀以确保不同提供商的模型有唯一名称
                model = f"{provider}_{model_name}" if provider else model_name
            else:
                # 如果没有激活的槽位，尝试获取第一个配置的槽位
                enabled_slots = config.get_enabled_slots('embedding')
                if enabled_slots:
                    slot_config = config.get_slot_config('embedding', enabled_slots[0])
                    provider = slot_config.get('provider', '')
                    model_name = slot_config.get('model_name', 'default_external')
                    model = f"{provider}_{model_name}" if provider else model_name
                else:
                    model = 'default_external'
        else:
            model = 'default'
        # 清理特殊字符
        return re.sub(r'[^a-zA-Z0-9_.-]', '_', model)

    def get_active_chat_slot_info(self) -> Dict[str, Any]:
        """
        获取当前激活的聊天槽位信息

        Returns:
            包含 slot_num, provider, model_name, display_name 的字典
        """
        self._check_and_refresh_config()

        if self.mode == 'external':
            enabled_slots = config.get_enabled_slots('chat')
            if enabled_slots:
                slot_num = enabled_slots[0]  # 获取优先级最高的槽位
                slot_config = config.get_slot_config('chat', slot_num)
                return {
                    'slot_num': slot_num,
                    'provider': slot_config.get('provider', ''),
                    'model_name': slot_config.get('model_name', ''),
                    'display_name': slot_config.get('display_name', '')
                }
        return {}

    def get_all_enabled_chat_slots(self) -> List[Dict[str, Any]]:
        """
        获取所有启用的聊天槽位信息（用于双模型对比）

        Returns:
            包含所有启用槽位信息的列表
        """
        self._check_and_refresh_config()

        if self.mode == 'external':
            enabled_slots = config.get_enabled_slots('chat')
            result = []
            for slot_num in enabled_slots:
                slot_config = config.get_slot_config('chat', slot_num)
                result.append({
                    'slot_num': slot_num,
                    'provider': slot_config.get('provider', ''),
                    'model_name': slot_config.get('model_name', ''),
                    'display_name': slot_config.get('display_name', '')
                })
            return result
        return []

    # --- 统一的公共接口 ---
    
    def chat_completion_stream(self, messages: List[Dict[str, str]], topic_id: int, **kwargs) -> Generator[str, None, None]:
        """执行流式聊天补全，内置上下文管理。"""
        self._check_and_refresh_config()

        if not self.chat_provider:
            if self.mode == 'external':
                raise RuntimeError("外部API未配置。请在⚙️系统设置页面配置至少一个提供商的API密钥。")
            else:
                raise RuntimeError(f"模式 '{self.mode}' 下没有可用的聊天服务。")

        # 上下文管理逻辑保持不变
        processed_messages, _ = self._manage_context_length(messages, topic_id)

        # 确保kwargs中包含 stream=True
        kwargs['stream'] = True

        # --- 获取流式响应 ---
        if self.mode == 'internal':
            # 内部服务模式
            client = OpenAI(base_url=self.service_config['llm']['url'], api_key=self.service_config['llm']['api_key'])
            model = self.service_config['llm']['model']

            try:
                stream = client.chat.completions.create(model=model, messages=processed_messages, **kwargs)
                for chunk in stream:
                    content = chunk.choices[0].delta.content
                    if content:
                        yield content
            finally:
                client.close()

        elif self.mode == 'external':
            # 外部API模式 - 使用选中的聊天模型
            selected = config.get_selected_model('chat')
            provider = selected.get('provider')
            model = selected.get('model')

            if not provider or not model:
                raise RuntimeError("未配置选中的聊天模型")

            client = getattr(self, f'{provider}_client', None)
            if not client:
                raise RuntimeError(f"未找到 {provider} 客户端")

            stream = client.chat.completions.create(model=model, messages=processed_messages, **kwargs)
            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    yield content

        elif self.mode == 'local':
            # Ollama
            url = f"{self.service_config['host']}/api/chat"
            payload = {"model": self.service_config['chat_model'], "messages": processed_messages, "stream": True, "options": kwargs}
            with requests.post(url, json=payload, stream=True) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line:
                        chunk = json.loads(line)
                        content = chunk.get('message', {}).get('content')
                        if content:
                            yield content
    
    def chat_completion(self, messages: List[Dict[str, str]], topic_id: int, **kwargs) -> Optional[str]:
        """
        主思考回路 - 重量级函数
        用于处理完整的用户对话，内置复杂的上下文管理和摘要逻辑。
        """
        self._check_and_refresh_config()
        
        if not self.chat_provider:
            raise RuntimeError(f"模式 '{self.mode}' 下没有可用的聊天服务。")
        
        processed_messages, stats = self._manage_context_length(messages, topic_id)
        
        response = self.chat_provider(processed_messages, **kwargs)
        
        # 将本次请求/响应的token统计信息返回
        # 可以在UI层使用
        if response:
            stats['response_tokens'] = count_tokens(response)
            stats['total_tokens'] = stats['request_tokens'] + stats['response_tokens']
        
        return response, stats
    
    def _lightweight_chat_completion(self, messages: List[Dict[str, str]], **kwargs) -> Optional[str]:
        """
        辅助思考回路 - 轻量级函数
        用于内部、一次性的任务，如生成标题、生成摘要。
        它直接调用 chat_provider，完全绕过复杂的上下文管理。
        """
        self._check_and_refresh_config()
        if not self.chat_provider:
            raise RuntimeError(f"模式 '{self.mode}' 下没有可用的聊天服务。")
        
        # 确保非流式
        # kwargs['stream'] = False
        
        # 直接调用，不进行任何处理
        response = self.chat_provider(messages, **kwargs)
        return response

    def get_embedding(self, content: Union[str, List[str]], **kwargs) -> Optional[Union[List[float], List[List[float]]]]:
        """执行文本向量化。"""
        self._check_and_refresh_config()
        
        if not self.embedding_provider:
            raise RuntimeError(f"模式 '{self.mode}' 下没有可用的Embedding服务。")
        return self.embedding_provider(content, **kwargs)

    def rerank(self, query: str, documents: List[str], **kwargs) -> Optional[List[int]]:
        """对文档列表根据查询进行重排序，返回排序后的索引。"""
        self._check_and_refresh_config()
        if not self.rerank_provider:
            logger.warning("当前模式下没有可用的Reranker服务，将跳过重排序。")
            return list(range(len(documents))) # 返回原始顺序
        return self.rerank_provider(query, documents, **kwargs)

    # --- 内部私有方法 (Internal Private Methods) ---
    # --- 上下文管理 ---
    def _manage_context_length(self, messages: List[Dict[str, str]], topic_id: int) -> Tuple[List[Dict[str, str]], Dict]:
        """
        此版本重构了核心算法，保证 system prompt 和最新的 user prompt 永远不会被丢弃。
        """
        budget = self.conversation_config.get('context_token_budget', 6000)
        
        # 1. 初始分解
        system_msgs = [m for m in messages if m['role'] == 'system']
        dialog_msgs = [m for m in messages if m['role'] in ['user', 'assistant']]
        
        if not dialog_msgs: # 如果没有任何对话（例如，只用于摘要的调用），则直接返回
            return system_msgs, {}

        # 2. 绝对保护最新一条用户消息
        latest_user_message = dialog_msgs.pop()
        past_history = dialog_msgs # dialog_msgs 现在只包含“过去”的历史

        # 3. 计算“不可变”部分（系统+最新问题）的Token，并计算“历史”的可用预算
        system_tokens = sum(count_tokens(m['content']) for m in system_msgs)
        latest_user_tokens = count_tokens(latest_user_message['content'])
        
        history_budget = budget - system_tokens - latest_user_tokens

        # 4. 从后往前（从新到旧）填充“过去的历史”
        final_history_msgs = []
        if history_budget > 0:
            temp_history_tokens = 0
            for msg in reversed(past_history):
                msg_tokens = count_tokens(msg['content'])
                if temp_history_tokens + msg_tokens > history_budget:
                    break
                final_history_msgs.insert(0, msg)
                temp_history_tokens += msg_tokens
        
        # 5. 判断是否需要【滚动更新】摘要
        num_kept_history = len(final_history_msgs)
        num_original_history = len(past_history)

        if num_kept_history < num_original_history:
            # 只有当“过去的历史”被截断时，才触发摘要
            cutoff_index = num_original_history - num_kept_history
            msgs_to_summarize_content = [f"{m['role']}: {m['content']}" for m in past_history[:cutoff_index]]
            
            existing_summary = db_manager.get_topic_summary(topic_id)
            
            text_for_new_summary = "\n".join(msgs_to_summarize_content)
            if existing_summary:
                text_for_new_summary = existing_summary + "\n\n" + text_for_new_summary
            
            self._generate_and_save_summary(text_for_new_summary, topic_id)

        # 6. 最终组装
        #    再次获取最新的摘要（可能是刚刚生成的）
        final_summary = db_manager.get_topic_summary(topic_id)
        if final_summary:
            summary_str = f"\n\n【前情提要】\n{final_summary}"
            # 合并到 system prompt 中
            if system_msgs and summary_str not in system_msgs[0]['content']:
                system_msgs[0]['content'] += summary_str

        # 最终消息 = 系统(含摘要) + 填充的历史 + 最新的问题
        final_messages = system_msgs + final_history_msgs + [latest_user_message]
        
        # 7. 计算最终请求Token
        final_request_tokens = sum(count_tokens(m['content']) for m in final_messages)
        stats = {"request_tokens": final_request_tokens}
        
        logger.info(f"上下文管理完成。最终发送 {len(final_messages)} 条消息，总请求Tokens: {final_request_tokens}")
        
        return final_messages, stats

    def _generate_and_save_summary(self, text_to_summarize: str, topic_id: int):
        """
        生成摘要，现在调用轻量级接口。
        """
        if not text_to_summarize.strip(): return
        
        summary_prompt = prompt_manager.render('summary_prompt.jinja2', dialogue_text=text_to_summarize)
        
        logger.info(f"为 Topic ID {topic_id} 生成或更新摘要...")
        try:
            summary_msgs = [{"role": "user", "content": summary_prompt}]
            
            new_summary_raw = self._lightweight_chat_completion(summary_msgs, temperature=0.1)
            if new_summary_raw:
                new_summary = cut_thinking_txt(new_summary_raw)
                db_manager.update_topic_summary(topic_id, new_summary)
                logger.info(f"Topic ID {topic_id} 的摘要已成功生成或更新。")
        except Exception as e:
            logger.error(f"生成和保存摘要失败: {e}", exc_info=True)

    # --- 各模式的具体实现 ---

    def _internal_chat_completion(self, messages: List[Dict[str, str]], **kwargs) -> Optional[str]:
        cfg = self.service_config['llm']
        client = OpenAI(base_url=cfg['url'], api_key=cfg['api_key'])
        try:
            completion = client.chat.completions.create(model=cfg['model'], messages=messages, **kwargs)
            # 使用 getattr 安全地访问属性  企业内网服务将思考部分内容分离了 response.choices[0].message.reasoning_content + "</think>"
            reasoning = getattr(completion.choices[0].message, 'reasoning_content', None)
            content = getattr(completion.choices[0].message, 'content', '')
            
            if reasoning:
                return f"{reasoning}</think>{content}"
            else:
                return content
            
        except APIError as e:
            logger.error(f"内部LLM API错误: {e}")
            raise  # 重新抛出，让上层捕获
        finally:
            client.close()

    def _internal_get_embedding(self, content: Union[str, List[str]], **kwargs) -> Optional[Union[List[float], List[List[float]]]]:
        cfg = self.service_config['embedding']
        client = OpenAI(base_url=cfg['url'], api_key=cfg['api_key'])
        try:
            response = client.embeddings.create(input=content, model=cfg['model'], **kwargs)
            embeddings = [d.embedding for d in response.data]
            return embeddings[0] if isinstance(content, str) else embeddings
        except APIError as e:
            logger.error(f"内部Embedding API错误: {e}")
            raise
        finally:
            client.close()

    def _internal_rerank(self, query: str, documents: List[str], **kwargs) -> List[int]:
        cfg = self.service_config['reranker']
        url = f"{cfg['url']}/rerank" # 假设reranker有自己的URL
        try:
            # 构建请求
            payload = {
                "query": query,
                "documents": documents,
                "model": cfg['model'], 
                "return_documents": True
            }
            
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            # 返回的格式是 {"results": [{"document": "...", "relevance_score": 0.8, "index": 2}]}
            # reranked_results = response.json().get("results", [])
            reranked_results = sorted(response.json()['results'], key=lambda x: x['relevance_score'], reverse=True)
            return [item['index'] for item in reranked_results]
        except Exception as e:
            logger.error(f"内部Reranker调用失败: {e}。返回原始顺序。")
            return list(range(len(documents)))
    
    def _external_chat_completion(self, messages: List[Dict[str, str]], **kwargs) -> Optional[str]:
        """使用选中的外部提供商进行聊天补全"""
        # 获取选中的聊天模型配置
        selected = config.get_selected_model('chat')
        provider = selected.get('provider')
        model = selected.get('model')

        if not provider or not model:
            logger.error("未配置选中的聊天模型")
            return None

        # 获取对应的客户端
        client = getattr(self, f'{provider}_client', None)
        if not client:
            logger.error(f"未找到 {provider} 客户端")
            return None

        try:
            completion = client.chat.completions.create(model=model, messages=messages, **kwargs)
            return completion.choices[0].message.content
        except APIError as e:
            logger.error(f"外部LLM API错误 ({provider}/{model}): {e}")
            raise

    def _external_get_embedding(self, content: Union[str, List[str]], **kwargs) -> Optional[Union[List[float], List[List[float]]]]:
        """使用选中的外部提供商进行向量化"""
        # 获取选中的embedding模型配置
        selected = config.get_selected_model('embedding')
        provider = selected.get('provider')
        model = selected.get('model')

        if not provider or not model:
            logger.error("未配置选中的Embedding模型")
            return None

        # 获取对应的客户端
        client = getattr(self, f'{provider}_client', None)
        if not client:
            logger.error(f"未找到 {provider} 客户端")
            return None

        # 获取模型的批处理大小限制
        model_config = config.get_model_config(provider, 'embedding', model)
        batch_size = model_config.get('batch_size', 10)

        try:
            is_single = isinstance(content, str)
            inputs = [content] if is_single else content

            # 如果输入数量超过限制，需要分批处理
            all_embeddings = []
            for i in range(0, len(inputs), batch_size):
                batch = inputs[i:i + batch_size]
                logger.debug(f"Embedding批处理: 处理第 {i//batch_size + 1} 批，包含 {len(batch)} 个文本")
                response = client.embeddings.create(input=batch, model=model, **kwargs)
                batch_embeddings = [d.embedding for d in response.data]
                all_embeddings.extend(batch_embeddings)

            return all_embeddings[0] if is_single else all_embeddings
        except APIError as e:
            logger.error(f"外部Embedding API错误 ({provider}/{model}): {e}")
            raise

    def _external_rerank(self, query: str, documents: List[str], **kwargs) -> List[int]:
        """
        使用选中的外部提供商进行文档重排序
        支持双Reranker混排：如果两个槽位都启用，则对两个模型的结果进行加权混合
        """
        # 获取所有启用的reranker槽位
        enabled_slots = config.get_enabled_slots('reranker')

        if not enabled_slots:
            logger.warning("未配置启用的Reranker槽位，返回原始顺序")
            return list(range(len(documents)))

        # 如果只有一个槽位启用，使用原来的逻辑
        if len(enabled_slots) == 1:
            return self._single_slot_rerank(query, documents, enabled_slots[0])
        else:
            # 两个槽位都启用，使用混排逻辑
            return self._hybrid_rerank(query, documents, enabled_slots)

    def _single_slot_rerank(self, query: str, documents: List[str], slot_num: int) -> List[int]:
        """使用单个槽位的reranker进行重排序"""
        slot_config = config.get_slot_config('reranker', slot_num)
        provider = slot_config.get('provider', '')
        model = slot_config.get('model_name', '')
        base_url = slot_config.get('base_url', '')
        api_key = slot_config.get('api_key', '')

        if not provider or not model:
            logger.warning(f"槽位 {slot_num} 未配置完整的Reranker模型，返回原始顺序")
            return list(range(len(documents)))

        if not base_url:
            logger.warning(f"槽位 {slot_num} 未配置Base URL，返回原始顺序")
            return list(range(len(documents)))

        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": model,
                "query": query,
                "documents": documents,
                "top_n": len(documents)
            }

            response = requests.post(base_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()

            result = response.json()
            logger.info(f"槽位{slot_num} rerank消耗token: {result.get('usage', {}).get('total_tokens', 'N/A')}, 模型: {result.get('model', model)}")

            # 解析返回结果
            reranked_results = sorted(result.get('results', []), key=lambda x: x.get('relevance_score', 0), reverse=True)
            return [item['index'] for item in reranked_results]

        except Exception as e:
            logger.error(f"槽位 {slot_num} Reranker API错误 ({provider}/{model}): {e}，返回原始顺序")
            return list(range(len(documents)))

    def _hybrid_rerank(self, query: str, documents: List[str], slot_nums: List[int]) -> List[int]:
        """
        双Reranker混排：调用两个槽位的reranker，对结果进行加权混合

        Args:
            query: 查询文本
            documents: 文档列表
            slot_nums: 启用的槽位编号列表

        Returns:
            混排后的文档索引列表
        """
        # 获取每个槽位的权重
        weights = {}
        for slot_num in slot_nums:
            slot_config = config.get_slot_config('reranker', slot_num)
            weights[slot_num] = slot_config.get('weight', 0.5)

        # 归一化权重，确保和为1
        total_weight = sum(weights.values())
        if total_weight == 0:
            weights = {slot: 0.5 for slot in slot_nums}
        else:
            weights = {slot: weight / total_weight for slot, weight in weights.items()}

        logger.info(f"使用混排Reranker，槽位权重: {weights}")

        # 调用每个槽位的reranker，收集每个文档的综合得分
        doc_scores = {i: 0.0 for i in range(len(documents))}

        for slot_num in slot_nums:
            slot_results = self._single_slot_rerank_with_scores(query, documents, slot_num)
            weight = weights[slot_num]

            # 根据排名计算分数（排名越前分数越高）
            for rank, doc_index in enumerate(slot_results):
                # 使用指数衰减：排名1得分1.0，排名2得分0.9，以此类推
                score = (1.0 / (1 + rank * 0.1)) * weight
                doc_scores[doc_index] += score

        # 按综合得分排序
        sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
        return [doc_index for doc_index, _ in sorted_docs]

    def _single_slot_rerank_with_scores(self, query: str, documents: List[str], slot_num: int) -> List[int]:
        """
        使用单个槽位的reranker进行重排序，并返回排序结果

        与 _single_slot_rerank 的区别是：
        - _single_slot_rerank 直接调用API并返回结果
        - _single_slot_rerank_with_scores 同样调用API，但可以用于混排场景
        """
        return self._single_slot_rerank(query, documents, slot_num)
            
    # def _local_chat_completion(self, messages: List[Dict[str, str]], **kwargs) -> Optional[str]:
    #     url = f"{self.service_config['host']}/api/chat"
    #     payload = {"model": self.service_config['chat_model'], "messages": messages, "stream": False, "options": kwargs}
    #     try:
    #         response = requests.post(url, json=payload, timeout=120)
    #         response.raise_for_status()
    #         return response.json()['message']['content']
    #     except requests.RequestException as e:
    #         logger.error(f"本地Ollama聊天请求失败: {e}")
    #         raise RuntimeError(f"无法连接到本地Ollama服务: {e}") from e
        
    def _local_chat_completion(self, messages: List[Dict[str, str]], **kwargs) -> Optional[str]:
        url = f"{self.service_config['host']}/v1"
        client = OpenAI(base_url=url, api_key="ollama")
        try:
            completion = client.chat.completions.create(model=self.service_config['chat_model'], messages=messages, **kwargs)
            # 使用 getattr 安全地访问属性  
            content = getattr(completion.choices[0].message, 'content', '')
            
            return content
            
        except APIError as e:
            logger.error(f"本地Ollama API错误: {e}")
            raise  # 重新抛出，让上层捕获
        finally:
            client.close()

    def _local_get_embedding(self, content: Union[str, List[str]], **kwargs) -> Optional[Union[List[float], List[List[float]]]]:
        url = f"{self.service_config['host']}/api/embeddings"
        is_single = isinstance(content, str)
        inputs = [content] if is_single else content
        embeddings = []
        try:
            for text in inputs:
                payload = {"model": self.service_config['embedding_model'], "prompt": text}
                response = requests.post(url, json=payload, timeout=60)
                response.raise_for_status()
                embeddings.append(response.json()['embedding'])
            return embeddings[0] if is_single else embeddings
        except requests.RequestException as e:
            logger.error(f"本地Ollama Embedding请求失败: {e}")
            raise RuntimeError(f"无法连接到本地Ollama Embedding服务: {e}") from e

    def _local_rerank(self, query: str, documents: List[str], **kwargs) -> List[int]:
        # Ollama 支持 rerank, 但需要单独的 endpoint/model
        # 假设有 /api/rerank 这样的 endpoint
        url = f"{self.service_config['host']}/api/rerank"
        payload = {"model": self.service_config['reranker_model'], "query": query, "documents": documents}
        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            # 返回的格式是 {"results": [{"document": "...", "relevance_score": 0.8, "index": 2}]}
            reranked_results = sorted(response.json()['results'], key=lambda x: x['relevance_score'], reverse=True)
            return [item['index'] for item in reranked_results]
        except Exception:
            # Ollama 的 rerank endpoint 并非标准，如果失败，则返回原始顺序
            logger.warning(f"本地Ollama Reranker调用失败或未配置。返回原始顺序。")
            return list(range(len(documents)))

# 创建一个全局实例
llm_service = LLMService()

