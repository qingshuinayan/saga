# Saga 🧠 - 您的专属AI专家智囊

Saga 是一款专为新能源汽车与人工智能领域的复合型专家设计的个人知识助手。它不仅仅是一个聊天机器人，更是一个能够深度融合您的专业知识、安全可靠、可随时迁移的本地化专家智囊。

Saga 的核心设计哲学是 "知识私有化" 和 "极致的便携性"。所有数据（包括您的文档、对话历史、向量索引）都存储在您的本地计算机上，确保了最高级别的安全与隐私。同时，它被设计为绿色软件，除了Python环境外，不依赖任何复杂的系统组件，可以轻松地在公司电脑和个人电脑之间迁移。

## 核心功能

| 图标 | 功能 | 详细说明 |
| :---: | :--- | :--- |
| 💬 | **智能对话** | 支持多轮上下文记忆和RAG（检索增强生成）。您可以在对话中上传临时文件（PDF、图片、TXT），Saga能够即时理解文件内容并就其进行问答。对话自动记忆使用的知识库，切换对话自动恢复。 |
| 📚 | **知识库管理** | 构建您个人的、持久化的知识体系。上传您的专业文档（PDF、TXT、Markdown等），Saga会将其向量化并存入本地向量数据库，供随时检索。知识库按服务模式智能过滤，确保向量模型兼容。 |
| ⚙️ | **多模式切换** | 提供三种LLM服务模式（`企业内网`、`外部API`、`本地Ollama`），每种模式独立的知识库和向量模型，可在系统设置中一键切换。 |
| 📊 | **上下文管理** | 智能监控对话长度，当超出Token预算时，自动生成对话摘要，确保长期对话的连贯性和效率，同时节省成本。 |
| 🎭 | **角色提示词** | 支持自定义系统提示词，按领域分类管理，打造不同角色的AI助手。 |
| 🛡️ | **数据本地化** | 您的所有知识库文件、向量数据、对话历史均存储在您自己的电脑上，确保了数据的绝对安全和私密性。 |

## 核心特性

### Slot-Based 双模型配置
- **双槽位架构**：每种服务类型（Chat、Embedding、Reranker、OCR）支持2个独立槽位
- **Chat**：双模型对比，左右分栏查看不同模型的回答
- **Embedding**：不同服务模式下向量库隔离，不同向量模型使用独立存储
- **Reranker**：支持双模型混排，加权融合提高检索质量
- **OCR**：优先级降级，主服务失败自动切换备用

### 智能模式切换
- 外部API模式：支持多家服务商（Qwen、DeepSeek、OpenAI等）
- 企业内网模式：MinerU高质量PDF解析
- 本地Ollama模式：多模态OCR支持，完全本地化

### 知识库对话记忆
- 自动保存每个对话使用的知识库
- 切换对话自动恢复知识库选择
- 智能过滤不兼容的知识库

## 技术架构

Saga 采用了一套轻量而强大的技术栈，确保了其高性能、易部署和易维护的特性。

### 前端框架
- **Streamlit** - 构建交互式Web界面，响应迅速，界面美观

### 后端核心
- **llm_service.py** - 封装了与大语言模型（LLM）、Embedding、Reranker和OCR等AI服务的交互逻辑，支持三种服务模式的无缝切换
- **knowledge_base.py** - 负责知识库的核心功能，包括文档的智能文本分割、向量化、存储和复杂的混合检索（语义相似性 + BM25关键词 + Reranker精排）
- **database.py** - 使用 **SQLite** 对所有元数据进行持久化管理
- **config.py** - 配置管理（单例模式），支持 slot-based 配置

### RAG 核心流程
1. **上传与解析**: 支持多种模式解析
   - 企业内网：MinerU → 内部OCR
   - 外部API：OCR Slot 1 → OCR Slot 2（降级）
   - 本地Ollama：多模态OCR → pdfplumber/PyPDF2（降级）
2. **分割与向量化**: `SmartTextSplitter` 智能分割，支持PDF章节保留，语义感知重叠
3. **存储**: 向量及元数据存入本地 **ChromaDB** 向量数据库
4. **检索与精排**: 混合检索（向量+BM25）+ 双Reranker混排
5. **生成**: 知识片段 + 对话历史 + 系统提示词 → LLM生成精准回答

### 向量隔离机制
不同 embedding 模型创建独立的向量集合：
```
kb_1_qwen_text-embedding-v4/   # 外部API模式的向量集合
kb_2_default_internal/          # 企业内网模式的向量集合
kb_3_default_local/             # 本地Ollama模式的向量集合
```

## 项目结构

```
saga/
│
├── 📜 main.py              # Streamlit应用主入口
├── 🚀 run_saga.bat         # Windows一键启动脚本
├── 📄 config.yaml          # 全局配置文件
├── 📦 requirements.txt     # Python依赖包列表
│
├── 📁 logs/                # 自动生成的日志文件目录
├── 📁 pages/               # Streamlit多页面应用目录
│   ├── 1_💬_智能对话.py       # 对话界面（含知识库记忆）
│   ├── 2_📚_知识库管理.py     # 知识库管理（含模式过滤）
│   ├── 3_📊_上下文管理.py     # 上下文管理与摘要
│   ├── 4_🎭_角色提示词.py     # 系统提示词管理
│   └── 5_⚙️_系统设置.py       # 系统设置（含模式切换）
├── 📁 prompts/             # 所有提示词模板目录
├── 📁 data/                # 所有持久化数据的存放目录
│   ├── 🗃️ saga.db          # SQLite数据库文件
│   ├── 📥 uploads/         # 用户上传的原始文档
│   ├── 📄 bm25_indices/    # BM25索引目录
│   └── 🧠 chroma_db/       # ChromaDB向量数据库目录
│
└── 📁 utils/               # 后端核心逻辑模块
    ├── 🔧 config.py         # 配置管理模块（单例模式）
    ├── 🗄️ database.py       # 数据库管理模块
    ├── 🤖 llm_service.py    # 【引擎】LLM服务模块（三种模式）
    ├── 📖 knowledge_base.py # 【引擎】知识库核心模块
    └── 🗒️ logging_config.py # 日志管理模块
```

## LLM 服务模式

### 1. 外部 API 模式（推荐）
适用于使用云端 LLM 服务的场景，支持多家服务商：

| 服务商 | Chat | Embedding | Reranker | OCR |
|--------|------|-----------|----------|-----|
| 🔵 阿里通义千问 | ✅ | ✅ | ✅ | ✅ |
| 🟢 DeepSeek | ✅ | ✅ | ❌ | ✅ |
| 🔴 OpenAI | ✅ | ✅ | ❌ | ✅ |
| 🟠 Anthropic | ✅ | ❌ | ❌ | ❌ |
| 🟡 Google | ✅ | ✅ | ❌ | ✅ |
| 🟣 智谱AI | ✅ | ✅ | ❌ | ✅ |

**特性**：
- 每种服务类型支持 2 个槽位
- Embedding 只能有一个激活（向量隔离）
- Reranker 可双槽混排
- OCR 支持优先级降级

### 2. 企业内网模式
适用于企业内部部署的场景：
- 使用企业内部 LLM 服务
- 支持 MinerU 高质量 PDF 解析（支持公式、表格）
- 配置由 IT 部门统一管理

### 3. 本地 Ollama 模式
适用于完全本地化的场景：
- 使用本地运行的 Ollama 服务
- 支持多模态 OCR（需要视觉模型如 qwen3-vl）
- 数据完全本地化，隐私性最好

## 安装与部署

本应用为Python项目，请确保您的系统中已安装 **Python 3.10 ~ 3.12**。

### 步骤 1: 下载项目

将本项目所有文件下载或克隆到您电脑的任意位置（压缩包直接解压缩放置），例如 `D:\Saga`。

### 步骤 2: 安装依赖

我们提供了一个批处理脚本来简化安装过程，它会自动设置国内镜像源以加快下载速度。

**Windows 用户**：
- **双击运行** 项目根目录下的 `install_dependencies.bat` 文件
- 脚本将自动完成所有Python包的安装，请耐心等待其执行完毕

**手动安装**：
```bash
pip install -r requirements.txt
```

### 步骤 3: 配置模型

在首次启动前，您需要配置AI模型服务。

#### 3.1 打开配置文件
编辑项目根目录下的 `config.yaml` 文件。

#### 3.2 选择服务模式
修改 `llm_service.active_mode` 来激活您选择的模式：
- `external` - 外部API服务（推荐）
- `internal` - 企业内网服务
- `local` - 本地Ollama服务

#### 3.3 配置外部API（推荐）
在 `llm_service.external` 下配置需要的槽位：

**Chat 模型配置**（必需）：
```yaml
llm_service:
  external:
    chat:
      slot_1:
        enabled: true
        provider: qwen  # 或 deepseek, openai 等
        base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
        api_key: sk-your-api-key-here  # 替换为您的API Key
        model_name: qwen-plus  # 或 deepseek-chat, gpt-4o 等
```

**Embedding 模型配置**（必需）：
```yaml
    embedding:
      slot_1:
        enabled: true
        active: true  # 设为当前激活的嵌入模型
        provider: qwen
        base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
        api_key: sk-your-api-key-here
        model_name: text-embedding-v4
        dimension: 1536
```

**Reranker 模型配置**（可选，推荐）：
```yaml
    reranker:
      slot_1:
        enabled: true
        provider: qwen
        base_url: https://dashscope.aliyuncs.com/compatible-api/v1/reranks
        api_key: sk-your-api-key-here
        model_name: qwen3-rerank
        weight: 0.6
```

**OCR 模型配置**（可选，用于文档解析）：
```yaml
    ocr:
      slot_1:
        enabled: true
        provider: qwen
        base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
        api_key: sk-your-api-key-here
        model_name: qwen-long
```

#### 3.4 配置企业内网模式
```yaml
llm_service:
  active_mode: internal
  internal:
    llm:
      model: Qwen3-235B-thinking
      url: https://your-internal-server/inference/v1
      api_key: your-api-key
    embedding:
      model: Qwen3-Embedding-8B
      url: https://your-internal-server/embedding/v1
      api_key: your-api-key
```

#### 3.5 配置本地Ollama模式
```yaml
llm_service:
  active_mode: local
  local:
    enabled: true
    host: http://localhost:11434
    chat_model: qwen3:0.6b
    embedding_model: qwen3-embedding:0.6b
    reranker_model: dengcao/Qwen3-Reranker-0.6B:Q8_0
    ocr_model: qwen3-vl:2b  # 多模态视觉模型，用于OCR
```

### 步骤 4: 启动应用

**Windows 用户**：
- **双击运行** 项目根目录下的 `run_saga.bat` 文件
- 应用启动后，会自动在您的默认浏览器中打开 `http://localhost:8501`

**手动启动**：
```bash
streamlit run main.py
```

## 使用指南

### 1. 首次使用流程

1. **启动应用**后，进入"系统设置"页面
2. **检查服务模式**是否正确，查看"系统状态"确认配置
3. **进入"知识库管理"**，创建您的第一个知识库
   - 知识库会自动使用当前激活的向量模型
4. **上传文档**到知识库，等待处理完成
5. **进入"智能对话"**，选择知识库，开始提问

### 2. 知识库管理

#### 按模式过滤显示
知识库管理页面会自动过滤，只显示与当前服务模式兼容的知识库：
- **外部API模式**：显示使用外部API embedding模型的知识库
- **企业内网模式**：显示使用内部embedding模型的知识库
- **本地Ollama模式**：显示使用本地embedding模型的知识库

#### 创建知识库
- 新建知识库会自动使用当前激活的向量模型
- 系统会显示"知识库创建成功！使用向量模型: xxx"
- 每个服务模式需要创建独立的知识库

### 3. 智能对话

#### 知识库选择记忆
- **新建对话**：知识库选择为空，需要手动选择
- **历史对话**：自动恢复之前使用的知识库
- **切换对话**：知识库选择自动恢复
- **更改选择**：自动保存到数据库，下次打开自动恢复
- **模式切换**：自动过滤不兼容的知识库

#### 临时文件上传
- 支持在对话中临时上传文件
- 支持 PDF、PNG、JPG、TXT、MD 格式
- 文件内容仅在当前对话中生效

### 4. 模式切换

#### 切换注意事项
- 不同模式的 embedding 模型不同
- 切换后需要为新模式创建新知识库
- 旧模式的知识库不会显示，但不会丢失数据

#### 推荐使用场景
- **外部API模式**：日常使用，响应快速，模型强大
- **企业内网模式**：公司内网环境，数据不出内网，支持MinerU
- **本地Ollama模式**：离线环境，数据完全本地，隐私性最好

## 高级功能

### 1. 双模型重排序
在"系统设置" → "重排序"中：
- 启用两个槽位，配置不同的 Reranker 模型
- 设置权重（如 0.6 和 0.4）
- 系统会自动混排两个模型的结果

### 2. OCR 降级机制
在"系统设置" → "文档解析"中：
- 配置两个 OCR 槽位
- Slot 1 作为主服务，Slot 2 作为备用
- 主服务失败时自动降级，提高解析成功率

### 3. 检索参数优化
在"系统设置" → "知识库设置"中：
- **Top-K**：初步检索数量（默认 10）
- **Top-N**：精排后数量（默认 3）
- **HyDE**：假设性文档嵌入，提高模糊查询效果
- **Agentic RAG**：查询分析与重写

## 注意事项

### 模型兼容性
- 不同服务模式的 embedding 模型不同
- 知识库与特定的 embedding 模型绑定
- 切换模式后需要创建新知识库并重新上传文档
- 系统会自动过滤，只显示兼容的知识库

### 首次运行
- 多模态 OCR 模型首次使用时可能需要下载
- 建议提前在 Ollama 中拉取所需的模型

### 数据备份
- `data` 目录包含了您的所有核心数据
- 为确保数据安全，建议定期手动备份此目录
- 包括 `saga.db`（数据库）、`chroma_db/`（向量库）、`uploads/`（上传文件）

### 依赖安装
- EasyOCR 是可选功能，用于图片 OCR
- 如需图片识别功能，请手动安装 PyTorch 和 EasyOCR
- 不安装也能正常处理 PDF、TXT、MD 等文件

## 常见问题

### Q1: 切换模式后知识库无法检索？
**A**: 不同模式的 embedding 模型不同，知识库界面只会显示兼容的知识库。请为新模式创建新知识库并重新上传文档。

### Q2: 知识库显示"未设置向量模型"？
**A**: 这通常是已修复的BUG。如仍有问题，请删除该知识库后重新创建，系统会自动使用当前向量模型。

### Q3: PDF 解析失败？
**A**:
- 外部API模式：检查 OCR 服务是否配置
- 企业内网模式：确保 MinerU 可用
- 本地Ollama模式：确保多模态模型（如 qwen3-vl）已下载
- 增加"系统设置"中的"解析超时时间"

### Q4: 检索结果不相关？
**A**:
- 启用 Reranker（在系统设置中配置）
- 调整 Top-K 和 Top-N 参数
- 启用 HyDE 或 Agentic RAG

### Q5: 如何测试配置是否正确？
**A**:
- 查看"系统设置"底部的"系统状态"
- 确保所有必需服务都显示配置信息
- 尝试进行一次对话测试

## 配置示例

### 阿里通义千问（推荐）
```yaml
llm_service:
  active_mode: external
  external:
    chat:
      slot_1:
        enabled: true
        provider: qwen
        base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
        api_key: sk-xxx  # 在阿里云控制台获取
        model_name: qwen-plus
    embedding:
      slot_1:
        enabled: true
        active: true
        provider: qwen
        base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
        api_key: sk-xxx
        model_name: text-embedding-v4
        dimension: 1536
```

### DeepSeek
```yaml
llm_service:
  active_mode: external
  external:
    chat:
      slot_1:
        enabled: true
        provider: deepseek
        base_url: https://api.deepseek.com/v1
        api_key: sk-xxx  # 在 DeepSeek 平台获取
        model_name: deepseek-chat
```

### 本地Ollama
```yaml
llm_service:
  active_mode: local
  local:
    enabled: true
    host: http://localhost:11434
    chat_model: qwen3:0.6b
    embedding_model: qwen3-embedding:0.6b
    ocr_model: qwen3-vl:2b
```

## 技术栈

- **前端**: Streamlit
- **数据库**: SQLite + ChromaDB
- **LLM**: OpenAI 兼容 API
- **文档解析**: MinerU, OCR, pdfplumber, PyPDF2
- **检索**: BM25 + 向量检索
- **向量隔离**: 每个模型独立存储

## 更新日志

### v1.0 (2026-02-05)
- ✨ Slot-Based 双模型配置架构
- ✨ 知识库对话记忆功能
- ✨ 本地Ollama多模态OCR支持
- ✨ 智能模式切换与知识库过滤
- 🐛 修复知识库创建时embedding_model为NULL
- 🐛 修复切换模式后智能对话报错
- 🐛 修复文档上传后的类型不匹配错误
- 📚 完善项目结构，调整页面顺序

---

**版本**: v1.0
**更新日期**: 2026-02-05
**维护者**: Saga 开发团队
