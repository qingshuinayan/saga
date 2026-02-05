# 📜 saga/utils/pydantic_models.py

from pydantic import BaseModel, Field
from typing import List, Literal

class QueryAnalysisResult(BaseModel):
    """
    定义了查询分析Agent的输出结构。
    这个模型的描述和字段描述将自动用于生成给LLM的指令。
    """
    action: Literal["search", "answer_directly"] = Field(
        ..., 
        description="根据用户查询意图，决定下一步是'search'(执行搜索)还是'answer_directly'(直接回答)。"
    )
    
    queries: List[str] = Field(
        ..., 
        description="一个优化后的查询列表，用于知识库搜索。如果action是'answer_directly'，则此列表应为空。"
    )

