"""cyber-egg · 免费 Token 探测器

统一 schema 定义。所有采集源最终都归一成 Provider 记录。
"""
from __future__ import annotations

# ---------------------------------------------------------------- 统一字段
# 每个 Provider 记录的字段清单（顺序即看板表格默认列序）
FIELDS = [
    "id",              # 统一 slug，跨源合并后的唯一标识
    "name",            # 展示名（优先中文）
    "name_en",         # 英文名（若有）
    "region",          # cn | global
    "kind",            # llm_api | cloud_platform | coding_tool | specialized_api
    "category",        # ongoing | trial | unknown
    "free_type",       # perpetual | renewing-quota | one-time | trial-credit | recurring-credit | unknown
    "free_quota",      # 免费额度描述（已清洗）
    "validity",        # 有效期描述
    "free_models",     # list[str] 免费模型 / 可用能力
    "rate_limits",     # 限速描述
    "preconditions",   # 前置条件
    "promotions",      # 限时活动
    "caveats",         # list[str] 分级陷阱 / 注意事项
    "card_required",   # 0 | 1 | None  是否必须绑卡
    "phone_required",  # 0 | 1 | None  是否必须手机/实名
    "commercial_ok",   # 0 | 1 | None  免费层是否允许商用
    "openai_compat",   # 0 | 1 | None  是否 OpenAI 兼容
    "base_url",        # OpenAI 兼容端点
    "env_key",         # 建议的环境变量名
    "homepage",        # 官网
    "docs_url",        # 官方额度文档
    "links",           # list[[label, url]] 官方链接集合
    "reviewed",        # 上游核验日期
    "quality",         # A | B | C | D  本工具计算的可用性分级
    "quality_reason",  # 分级理由（可解释）
    "sources",         # list[str] 数据来源 key
    "first_seen",      # 本工具首次收录日期
    "last_changed",    # 本工具检测到最后变化的日期
    "changed_fields",  # list[str] 最近一次变化涉及的字段
]

# 参与变更检测的字段（噪声大或每次都变的字段排除在外）
DIFF_FIELDS = [
    "name", "region", "kind", "category", "free_type", "free_quota",
    "validity", "free_models", "rate_limits", "preconditions",
    "promotions", "caveats", "card_required", "phone_required",
    "commercial_ok", "openai_compat", "base_url", "reviewed", "quality",
]

# ---------------------------------------------------------------- 数据源注册
# 源清单已移至 config/sources.json（可在库区启停与改地址），
# 这里只保留一份映射供需要时反查。

# ---------------------------------------------------------------- 跨源别名
# key = intel 的 vendor id, value = paco 的 slug
# 用于把两个源的同一厂商合并成一条记录
ALIAS_INTEL_TO_PACO = {
    "google_gemini": "google-gemini",
    "groq": "groq",
    "openrouter": "openrouter",
    "cloudflare_workers_ai": "cloudflare-workers-ai",
    "cohere": "cohere",
    "cerebras": "cerebras",
    "mistral": "mistral",
    "huggingface": "huggingface",
    "siliconflow": "siliconflow",
    "zhipu_glm": "zai-glm",
    "ibm_watsonx": "ibm-watsonx",
    "fireworks_ai": "fireworks-ai",
    "baseten": "baseten",
    "nebius": "nebius",
    "ai21_labs": "ai21",
    "nvidia_nim": "nvidia-nim",
    "jina_ai": "jina-ai",
    "poolside": "poolside",
    "aliyun_qwen": "alibaba-model-studio",
    "tencent_hunyuan": "tencent-hunyuan",
    "modal": "modal",
    "deepinfra": "deepinfra",
    "together_ai": "together-ai",
}

# intel 的 part → (region, kind) 映射
INTEL_PART_MAP = {
    1: ("cn", "llm_api"),          # 国内开放平台
    2: ("global", "llm_api"),      # 海外开放平台
    3: ("global", "cloud_platform"),  # 云厂商托管
    4: ("cn", "coding_tool"),      # AI 编程工具（多为国内，含少量海外）
}

# part 4 里的海外编程工具需要单独纠正 region
INTEL_PART4_GLOBAL = {"github_copilot", "cursor_ide", "kiro", "zed", "qoder"}

# 判定为中国厂商的 paco slug（paco 主体是海外，只有少数国内）
PACO_CN_SLUGS = {
    "siliconflow", "zai-glm", "alibaba-model-studio", "tencent-hunyuan",
    "modelscope",
}

# paco 里属于「专用能力 API」而非通用大模型的 slug
PACO_SPECIALIZED = {
    "deepgram", "assemblyai", "speechmatics", "speechify", "hume-ai",
    "unreal-speech", "elevenlabs", "sarvam-ai", "gladia", "rime",
    "cartesia", "fish-audio", "rev-ai", "voicegain", "smallest-ai",
    "retell-ai", "twelve-labs", "ocr-space", "llamaparse", "nanonets",
    "moondream", "unstructured", "nutrient", "photoroom", "veryfi",
    "datalab", "runware", "pinecone-inference", "voyage-ai",
    "contextual-ai", "mixedbread", "clarifai", "wandb-inference",
    "camb-ai", "upstage", "typhoon", "arli-ai", "nlpcloud", "sambanova",
    "scaleway", "vercel-ai-gateway", "ai-horde", "pollinations",
    "ollama-cloud",
}

# free_type 中文标签
FREE_TYPE_LABEL = {
    "perpetual": "永久免费",
    "renewing-quota": "周期刷新",
    "one-time": "一次性赠送",
    "trial-credit": "试用额度",
    "recurring-credit": "循环积分",
    "unknown": "未标注",
}

REGION_LABEL = {"cn": "国内", "global": "海外"}
KIND_LABEL = {
    "llm_api": "大模型平台",
    "cloud_platform": "云厂商",
    "coding_tool": "编程工具",
    "specialized_api": "专用 API",
}
QUALITY_LABEL = {
    "A": "可长期白嫖",
    "B": "可用但有门槛",
    "C": "一次性 / 需充值",
    "D": "未核实 / 不可外带",
}

# ---------------------------------------------------------------- 圈层划分
# 「第一梯队」：御三家 + 国内头部。这是用户视角的「主流前沿」，不等于分级高低。
TIER1_VENDORS = {
    # 御三家
    "openai", "anthropic", "google_gemini",
    # 国内头部
    "deepseek", "aliyun_qwen", "zhipu_glm", "moonshot_kimi",
    "volcengine_doubao", "minimax", "tencent_hunyuan", "baidu_qianfan",
    # 第一梯队里的横向产品线（归属于上述厂商）
    "nano_banana", "seedance", "doubao_coding", "workbuddy_cn", "workbuddy_intl",
}

# 国内厂商（用于「国内头部」细分）
TIER1_CN_VENDORS = {
    "deepseek", "aliyun_qwen", "zhipu_glm", "moonshot_kimi",
    "volcengine_doubao", "minimax", "tencent_hunyuan", "baidu_qianfan",
}

TIER1_LABEL = "第一梯队"
TIER1_DESC = "御三家 + 国内头部"

# ---------------------------------------------------------------- 模态
# 生成式 AI 不只有文本。图像 / 视频类福利的计量单位是「张 / 段 / 秒」，
# 与 token 不同，必须单独标记，否则会被当成 LLM 额度混在一起看。
MODALITIES = {
    "text":  {"label": "文本", "icon": "T", "color": "#0d8b7f"},
    "image": {"label": "图像", "icon": "▣", "color": "#7048c8"},
    "video": {"label": "视频", "icon": "▶", "color": "#d4573f"},
    "audio": {"label": "语音", "icon": "♪", "color": "#2b62d9"},
    "design": {"label": "设计", "icon": "✦", "color": "#c0700c"},
}

# 有生成式模态（非纯文本）的厂商，用于「图像视频」筛选
MULTIMODAL_VENDORS = {
    "seedance", "nano_banana", "lovart", "jimeng", "kling",
    "volcengine_doubao", "google_gemini", "aliyun_qwen", "zhipu_glm",
}
