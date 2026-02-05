# Saga 个人知识助手 - 进度说明文档

## 📋 目录

1. [Phase 实施进度总结](#phase-实施进度总结)
2. [本次修复内容](#本次修复内容)
3. [待优化项与建议](#待优化项与建议)
4. [系统功能逻辑说明](#系统功能逻辑说明)
5. [使用帮助说明](#使用帮助说明)

---

## Phase 实施进度总结

### Phase 1: 制定详细实施计划 ✅
**状态**: 已完成

**内容**:
- 设计了完整的 slot-based 配置架构
- 规划了 10 个实施阶段
- 明确了各服务类型（chat、embedding、reranker、ocr）的双槽位支持方案

### Phase 2: 重构配置结构（支持双模型配置）✅
**状态**: 已完成

**内容**:
- `config.yaml` 重构为 slot-based 架构
- 每个服务类型支持 2 个独立槽位
- 每个槽位包含：enabled、priority、provider、base_url、api_key、model_name
- 添加了 `provider_presets` 预设配置

### Phase 3: 更新系统设置页面UI ✅
**状态**: 已完成

**内容**:
- 完全重写 `pages/5_⚙️_系统设置.py`
- 实现了按服务类型组织的 Tab 界面
- 每个服务类型显示两个槽位的配置
- 简化模型配置为单输入框（移除复杂下拉选择）

**优化记录**:
- ✅ 移除 Reranker 的"批处理大小"配置项
- ✅ 移除 OCR 的"向量维度"配置项
- ✅ 修复服务类型特定字段的保存逻辑

### Phase 4: 智能对话页面双模型左右分栏 ⏸️
**状态**: 待实施

**原因**: 需要大量 UI 修改，暂延后

**计划**:
- 对话页面左右分栏显示两个模型输出
- 独立的 token 追踪
- 模型选择器

### Phase 5: 知识库向量模型隔离提示 ✅
**状态**: 已完成

**内容**:
- `utils/database.py` 添加 `embedding_model` 字段
- 不同 embedding 模型创建独立的向量集合
- 知识库与嵌入模型绑定
- 模式切换时提示重新索引

### Phase 6: 重排序双模型混排 ✅
**状态**: 已完成

**内容**:
- `utils/llm_service.py` 实现 `_hybrid_rerank()` 方法
- 两个 reranker 槽位可同时激活
- 支持权重配置（weight 参数）
- 指数衰减评分算法混合结果

### Phase 7: 文档解析优先级与降级 ✅
**状态**: 已完成

**内容**:
- `utils/llm_service.py` 实现 OCR 优先级降级
- 优先使用 slot_1，失败则自动尝试 slot_2
- 记录解析来源和警告信息
- 支持多模态模型解析

### Phase 8: 模式切换检测与提示 ✅
**状态**: 已完成

**内容**:
- `utils/config.py` 实现配置验证方法
- External 模式：只检查 chat 和 embedding 为必需服务
- Internal 模式：只检查 LLM 和 Embedding URL 必需配置
- Reranker 和 OCR 作为可选服务
- 模式切换时提供详细警告信息

### Phase 9: RAG 能力优化增强 ✅
**状态**: 已完成

**内容**:
- `utils/knowledge_base.py` 实现 `SmartTextSplitter`
- 文档类型感知（PDF、Markdown、普通文本）
- PDF 章节结构保留
- 语义感知重叠分割
- 动态块大小调整

### Phase 10: 系统审查与 BUG 修复 ✅
**状态**: 已完成

**内容**:
- 代码审查和优化
- BUG 修复
- UI 简化

---

## 本次修复内容（2026-02-03）

### 1. 配置项优化
**问题**: Reranker 和 OCR 配置中存在不必要的字段

**修复**:
- 移除 Reranker 的"批处理大小"配置项
- 移除 OCR 的"向量维度"配置项
- 更新保存逻辑，每个服务类型只保存必要的字段

### 2. 本地Ollama OCR支持
**新增功能**: 本地Ollama模式支持多模态OCR

**实现**:
- `config.yaml` 添加 `local.ocr_model` 配置项
- `utils/llm_service.py` 添加 `_local_ollama_ocr()` 方法
- Local 模式下优先使用 Ollama 多模态模型（如 qwen3-vl:2b）
- PDF 文件自动转换为图片后进行 OCR 识别
- OCR 失败时自动降级到 pdfplumber/PyPDF2

### 3. 知识库模式过滤
**问题**: 知识库界面显示所有知识库，没有按服务模式过滤

**修复**:
- 知识库管理页面只显示与当前模式兼容的知识库
- 添加"其他模式的知识库"折叠区域
- 添加"未设置向量模型的知识库"警告区域
- 智能对话页面的知识库选择器也只显示兼容知识库

### 4. 对话知识库记忆
**问题**: 切换对话时知识库选择不恢复

**实现**:
- 数据库添加 `conversation_topics.knowledge_bases` 字段
- 新建对话时清空知识库选择
- 历史对话自动恢复之前使用的知识库
- 知识库选择变更时自动保存到数据库
- 切换服务模式时自动过滤不兼容的知识库

### 5. 页面顺序调整
**优化**: 将系统设置移到第5位

**变更**:
- `4_⚙️_系统设置.py` → `5_⚙️_系统设置.py`
- `5_🎭_角色提示词.py` → `4_🎭_角色提示词.py`

### 6. BUG修复：知识库创建时embedding_model为NULL
**问题**: 新创建的知识库 embedding_model 字段为 NULL

**修复**:
- 创建知识库时自动传入当前激活的向量模型
- 添加成功提示显示使用的向量模型
- 修改过滤逻辑使用 `.get()` 安全访问字段

### 7. BUG修复：切换模式后智能对话报错
**问题**: StreamlitAPIException - default value not in options

**修复**:
- 切换对话时重置知识库选择初始化标志
- 每次渲染时过滤掉不兼容的知识库选择
- 确保 default 值始终在 options 范围内

### 8. BUG修复：SmartTextSplitter返回值类型不匹配
**问题**: `split_text()` 返回字典列表，但 `add_chunks_to_file()` 期望字符串列表

**修复**:
- 从字典列表中提取 `text` 字段用于数据库存储
- 保留 `metadata` 用于 ChromaDB 存储
- 统一使用 `chunk_texts` 变量名

---

## 待优化项与建议

### 1. Phase 4: 双模型对比 UI（待实施）
**优先级**: 中

**说明**: 需要修改对话页面，实现左右分栏对比两个模型的输出

**建议**:
- 在对话页面侧边栏添加模型选择器
- 使用 columns 布局实现左右分栏
- 独立追踪每个模型的 token 使用量
- 添加"合并视图"和"对比视图"切换

### 2. 配置导入/导出功能
**优先级**: 低

**说明**: 支持配置的导入导出，方便备份和迁移

**建议**:
- 添加"导出配置"按钮，生成 YAML 文件
- 添加"导入配置"功能，支持上传 YAML 文件
- 提供"重置为默认配置"选项

### 3. API Key 加密存储
**优先级**: 中

**说明**: 当前 API Key 明文存储在配置文件中

**建议**:
- 使用环境变量或加密存储 API Key
- 添加 API Key 掩码显示功能
- 提供"测试连接"功能验证配置

### 4. 知识库重新索引工具
**优先级**: 高

**说明**: 当切换 embedding 模型时需要手动重新上传文件

**建议**:
- 在知识库管理页面添加"重新索引"按钮
- 自动检测向量模型不匹配并提示
- 批量重新索引所有知识库

### 5. 对话历史搜索
**优先级**: 中

**说明**: 当前只能浏览对话历史，不支持搜索

**建议**:
- 添加对话内容全文搜索
- 按时间范围筛选对话
- 导出对话记录为 Markdown 或 PDF

### 6. 多模态内容支持增强
**优先级**: 低

**说明**: 当前对图片和表格的处理可能不够完善

**建议**:
- 增强图片描述和索引
- 支持表格内容提取和结构化存储
- 添加多模态检索结果预览

---

## 系统功能逻辑说明

### 1. 系统架构

```
Saga 个人知识助手
├── 前端界面 (Streamlit)
│   ├── 1_💬_智能对话.py          # 对话界面
│   ├── 2_📚_知识库管理.py        # 知识库管理
│   ├── 3_📊_上下文管理.py        # 上下文管理
│   ├── 4_🎭_角色提示词.py        # 角色提示词
│   └── 5_⚙️_系统设置.py          # 系统设置
│
├── 核心服务层
│   ├── llm_service.py            # LLM服务封装
│   ├── knowledge_base.py         # 知识库管理
│   └── database.py               # 数据库管理
│
├── 配置层
│   └── config.py                 # 配置管理（单例模式）
│
└── 配置文件
    └── config.yaml               # YAML配置文件
```

### 2. LLM 服务模式

#### 2.1 外部 API 模式（External）
- 支持 4 种服务类型：Chat、Embedding、Reranker、OCR
- 每种服务类型支持 2 个槽位
- 槽位独立配置：provider、base_url、api_key、model_name

**特性**:
- **Chat**: 两槽位可同时激活，用于模型对比
- **Embedding**: 只能有一个槽位激活（向量库隔离）
- **Reranker**: 两槽位可同时激活，支持加权混排
- **OCR**: 按优先级降级（slot_1 → slot_2）

#### 2.2 企业内网模式（Internal）
- 使用企业内部部署的 LLM 服务
- 支持 MinerU 高质量 PDF 解析
- 配置由 IT 部门统一管理

#### 2.3 本地 Ollama 模式（Local）
- 使用本地运行的 Ollama 服务
- 数据完全本地化，隐私性好
- 支持多模态 OCR（需要视觉模型如 qwen3-vl）
- OCR 失败时自动降级到本地库解析

### 3. Slot-Based 配置系统

#### 3.1 配置结构
```yaml
llm_service:
  active_mode: external
  external:
    chat:
      slot_1:
        enabled: true
        priority: 1
        provider: qwen
        base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
        api_key: sk-xxx
        model_name: qwen-plus
      slot_2:
        enabled: false
        priority: 2
        ...
```

#### 3.2 配置访问方法
```python
# 获取槽位配置
config = Config()
slot_config = config.get_slot_config('chat', 1)

# 设置槽位配置
config.set_slot_config('chat', 1, {
    'enabled': True,
    'provider': 'qwen',
    'model_name': 'qwen-plus',
})

# 获取启用的槽位
enabled_slots = config.get_enabled_slots('chat')

# 检查槽位是否配置
is_configured = config.is_slot_configured('chat', 1)
```

### 4. RAG 检索流程

```
用户问题
    ↓
查询分析（Agentic RAG）
    ↓
HyDE 假设性文档生成（可选）
    ↓
混合检索
    ├── 向量检索（ChromaDB）
    └── 关键词检索（BM25）
    ↓
重排序（Reranker）
    ├── 单模型重排
    └── 双模型混排
    ↓
上下文构建
    ↓
LLM 生成回答
```

### 5. 知识库向量隔离

不同 embedding 模型创建独立的向量集合：

```
knowledge_bases (数据库)
    ├── id: 1, name: "AI科技", embedding_model: "qwen_text-embedding-v4"
    ├── id: 2, name: "内部文档", embedding_model: "default_internal"
    └── id: 3, name: "本地知识", embedding_model: "default_local"

每个知识库使用对应模型的独立向量集合
```

### 6. 文档解析策略

#### 6.1 企业内网模式
```
PDF 文档
    ↓
优先使用 MinerU
    ├── 成功 → 返回结构化内容（支持公式、表格）
    └── 失败 → 降级到内部 OCR 服务
```

#### 6.2 外部 API 模式
```
PDF 文档
    ↓
使用配置的 OCR 服务
    ├── Slot 1 尝试
    └── Slot 2 降级（如果 Slot 1 失败）
```

#### 6.3 本地 Ollama 模式
```
PDF/图片文档
    ↓
优先使用 Ollama 多模态 OCR
    ├── 成功 → 返回识别文本
    └── 失败 → 降级到 pdfplumber/PyPDF2/easyocr
```

### 7. 配置验证与模式切换

#### 7.1 配置验证规则
- **External**: chat 和 embedding 必须配置
- **Internal**: LLM 和 Embedding URL 必须配置
- **Local**: host、chat_model、embedding_model 必须配置

#### 7.2 模式切换警告
- 从 External 切换到其他模式：提醒知识库可能需要重新索引
- 配置不完整：显示详细警告信息

### 8. 知识库对话记忆机制

```
对话表 (conversation_topics)
    ├── id: 1
    ├── title: "关于AI的讨论"
    └── knowledge_bases: "[1, 2]"  # JSON格式存储知识库ID列表

切换对话时：
    1. 读取 knowledge_bases 字段
    2. 恢复兼容的知识库选择
    3. 过滤掉不兼容的知识库

更改选择时：
    1. 自动保存到数据库
    2. 下次打开自动恢复
```

---

## 使用帮助说明

### 1. 首次使用配置

#### 1.1 安装依赖
```bash
# Windows: 双击运行
install_dependencies.bat

# 或手动安装
pip install -r requirements.txt
```

#### 1.2 配置 LLM 服务
1. 打开"系统设置"页面
2. 选择服务模式（推荐：外部API）
3. 配置 Chat 模型槽位：
   - 启用槽位 1
   - 选择提供商（如：阿里通义千问）
   - 填写 Base URL（通常会自动填充）
   - 填写 API Key
   - 填写模型名称（如：qwen-plus）
   - 点击"保存"

#### 1.3 配置 Embedding 模型
1. 切换到"向量化"标签页
2. 启用槽位 1
3. 配置提供商和 API Key
4. 勾选"设为当前激活的嵌入模型"
5. 设置向量维度（根据模型设置，如 1536）
6. 点击"保存"

#### 1.4 可选配置
- **Reranker**: 提高检索质量，推荐配置
- **OCR**: 用于文档解析，如果需要上传 PDF/图片则配置

### 2. 创建知识库

1. 进入"知识库管理"页面
2. 页面会显示当前服务模式和向量模型
3. 点击"创建新知识库"
4. 填写知识库名称和描述
5. 点击"创建"

**注意**: 创建的知识库会自动使用当前激活的向量模型，并在知识库列表中显示。

### 3. 上传文档

1. 在"知识库管理"页面选择目标知识库
2. 点击"上传文件"
3. 选择文件（支持 PDF、Markdown、TXT、PNG、JPG）
4. 点击"开始处理上传的文件"
5. 等待解析和向量化完成

### 4. 智能对话

1. 进入"智能对话"页面
2. 在侧边栏选择知识库（只显示当前模式下兼容的知识库）
3. 输入问题
4. 系统会：
   - 检索相关文档
   - 重排序结果
   - 生成回答（引用来源）

**对话知识库记忆**:
- 新建对话：知识库选择为空，需要手动选择
- 历史对话：自动恢复之前使用的知识库
- 切换对话：知识库选择会自动恢复
- 更改选择：自动保存，下次打开自动恢复

### 5. 模式切换

#### 5.1 从外部API切换到企业内网
1. 在"系统设置"页面切换模式
2. 系统会验证配置是否完整
3. 如果知识库使用了外部API的向量模型，会提示需要重新索引

#### 5.2 从外部API切换到本地Ollama
1. 确保本地 Ollama 已启动
2. 配置 Ollama 服务地址和模型名称
3. 切换模式后，知识库需要重新创建

### 6. 高级功能

#### 6.1 双模型重排序
1. 在"系统设置" → "重排序"中启用两个槽位
2. 配置不同的 Reranker 模型
3. 设置权重（如 0.6 和 0.4）
4. 系统会自动混排两个模型的结果

#### 6.2 OCR 降级
1. 在"系统设置" → "文档解析"中配置两个槽位
2. Slot 1 作为主解析服务
3. Slot 2 作为备用（自动降级）

#### 6.3 检索参数调整
- **Top-K**: 初步检索数量（默认 10）
- **Top-N**: 精排后数量（默认 3）
- **HyDE**: 启用假设性文档嵌入
- **Agentic RAG**: 启用查询分析与重写

### 7. 常见问题

#### Q1: 切换模式后知识库无法检索？
**A**: 不同模式的 embedding 模型不同，知识库界面只会显示兼容的知识库。需要为新模式创建新知识库并重新上传文档。

#### Q2: 新建知识库显示"未设置向量模型"？
**A**: 这个BUG已修复。如果仍有问题，请删除该知识库后重新创建，系统会自动使用当前向量模型。

#### Q3: PDF 解析失败？
**A**:
- 外部API模式：检查 OCR 服务是否配置
- 企业内网模式：确保 MinerU 可用
- 本地Ollama模式：确保多模态模型已下载
- 增加"解析超时时间"

#### Q4: 检索结果不相关？
**A**:
- 启用 Reranker
- 调整 Top-K 和 Top-N 参数
- 启用 HyDE 或 Agentic RAG

#### Q5: 智能对话页面报错 "default value not in options"？
**A**: 这个BUG已修复。现在切换服务模式后会自动过滤不兼容的知识库。

### 8. 配置示例

#### 8.1 阿里通义千问配置
```yaml
provider: qwen
base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
api_key: sk-xxx  # 在阿里云控制台获取
chat_model: qwen-plus
embedding_model: text-embedding-v4
reranker_model: qwen3-rerank
```

#### 8.2 DeepSeek 配置
```yaml
provider: deepseek
base_url: https://api.deepseek.com/v1
api_key: sk-xxx  # 在 DeepSeek 平台获取
chat_model: deepseek-chat
embedding_model: deepseek-text-embedding
```

#### 8.3 本地Ollama配置
```yaml
local:
  host: http://localhost:11434
  chat_model: qwen3:0.6b
  embedding_model: qwen3-embedding:0.6b
  reranker_model: dengcao/Qwen3-Reranker-0.6B:Q8_0
  ocr_model: qwen3-vl:2b
```

---

## 附录

### A. 文件结构
```
saga/
├── main.py                    # 应用入口
├── config.yaml                # 配置文件
├── requirements.txt           # Python 依赖
├── pages/                     # Streamlit 页面
│   ├── 1_💬_智能对话.py
│   ├── 2_📚_知识库管理.py
│   ├── 3_📊_上下文管理.py
│   ├── 4_🎭_角色提示词.py
│   └── 5_⚙️_系统设置.py
├── utils/                     # 工具模块
│   ├── config.py              # 配置管理
│   ├── llm_service.py         # LLM 服务
│   ├── knowledge_base.py      # 知识库
│   ├── database.py            # 数据库
│   └── logging_config.py      # 日志配置
├── data/                      # 数据目录
│   ├── saga.db                # SQLite 数据库
│   ├── chroma_db/             # 向量数据库
│   ├── bm25_indices/          # BM25 索引
│   ├── uploads/               # 上传文件
│   └── backups/               # 备份
└── logs/                      # 日志文件
```

### B. 支持的服务提供商
- 🔵 阿里通义千问 (Qwen)
- 🟢 DeepSeek
- 🔴 OpenAI (GPT)
- 🟠 Anthropic (Claude)
- 🟡 Google (Gemini)
- 🟣 智谱AI (GLM)
- ⚪ 其他/自定义

### C. 技术栈
- **前端**: Streamlit
- **数据库**: SQLite + ChromaDB
- **LLM**: OpenAI 兼容 API
- **文档解析**: MinerU, OCR, pdfplumber, PyPDF2
- **检索**: BM25 + 向量检索

### D. 页面功能说明

#### 1. 智能对话
- 多轮对话记忆
- 知识库检索
- 临时文件上传
- Token 统计
- 对话历史管理
- 知识库选择记忆

#### 2. 知识库管理
- 按服务模式过滤显示
- 创建知识库（自动使用当前向量模型）
- 上传文档
- 查看文件列表
- 删除文件

#### 3. 上下文管理
- 查看所有对话摘要
- 管理对话历史
- Token 预算管理

#### 4. 角色提示词
- 自定义系统提示词
- 按领域分类管理

#### 5. 系统设置
- LLM 服务模式切换
- 外部API槽位配置
- 本地Ollama配置（含OCR）
- 知识库参数调整
- 对话参数调整
- 系统状态查看

---

**文档版本**: v2.1
**更新日期**: 2026-02-03
**维护者**: Saga 开发团队
