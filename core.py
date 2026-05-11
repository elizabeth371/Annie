# ============================================================
# 外贸采购比价助手 - 核心业务逻辑层 (core.py)
# 遵循 MVC 架构，本模块不包含任何 Streamlit/界面相关代码
# 所有数据处理、PDF解析、AI交互、业务规则均在此实现
# ============================================================

import io
import json
import logging
import os
from typing import Any, Dict, List, Optional

import pandas as pd
import pdfplumber
from openai import OpenAI

# --------------------- 日志配置 ---------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ============================================================
# 常量定义
# ============================================================

# ---- 需要从PDF中提取的目标字段及其中文说明 ----
EXTRACTION_FIELDS: Dict[str, str] = {
    "厂家名称": "厂家名称 / 制造商 / Manufacturer",
    "屏幕尺寸": '屏幕尺寸（如55"、65"、75"、86"等）',
    "亮度(cd/m²)": "屏幕亮度，单位 cd/m² 或 nits",
    "触控技术": "触控技术（如红外、电容、电磁、光学等）",
    "安卓版本": "内置安卓系统版本（如 Android 11 / 12 / 13）",
    "CPU型号": "处理器型号（如 RK3588、MTK、Amlogic、Qualcomm 等）",
    "内存/存储": "RAM 与 ROM 配置（如 4GB+32GB）",
    "是否含OPS": "是否包含 OPS（可插拔式电脑模块），取值为 是/否/选配",
    "认证信息": "产品认证列表（如 CE、FCC、SASO、RoHS、CCC 等）",
}

# ---- 默认值：当 AI 无法提取字段时使用 ----
DEFAULT_VALUES: Dict[str, str] = {
    "厂家名称": "未知厂家",
    "屏幕尺寸": "未提供",
    "亮度(cd/m²)": "未提供",
    "触控技术": "未提供",
    "安卓版本": "未提供",
    "CPU型号": "未提供",
    "内存/存储": "未提供",
    "是否含OPS": "未提供",
    "认证信息": "未提供",
}

# ---- 多平台 AI 服务商配置 ----
# 所有平台均支持 OpenAI 兼容 API 协议
# 获取 Key 的指引请参考 README 或侧边栏「💡 如何获取免费 Key？」
AI_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "阿里云 (免费额度)": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_placeholder": "sk-xxxxxxxxxxxxxxxx",  # 在阿里云 DashScope 控制台获取
        "models": ["qwen-turbo", "qwen-plus", "qwen-max"],
        "default_model": "qwen-turbo",
        "free_note": "阿里云 DashScope 为 qwen-turbo 等模型提供免费额度。"
                       "注册地址: https://dashscope.console.aliyun.com/",
    },
    "百度 (免费额度)": {
        "base_url": "https://qianfan.baidubce.com/v2",
        "api_key_placeholder": "请输入百度千帆 API Key",
        "models": ["ernie-speed", "ernie-lite", "ernie-4.0"],
        "default_model": "ernie-speed",
        "free_note": "百度千帆为 ERNIE-Speed 等模型提供免费额度。"
                       "注册地址: https://console.bce.baidu.com/qianfan/",
    },
    "硅基流动 (低价)": {
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key_placeholder": "sk-xxxxxxxxxxxxxxxx",
        "models": ["deepseek-ai/DeepSeek-V2", "deepseek-ai/DeepSeek-V3",
                    "Qwen/Qwen2.5-7B-Instruct"],
        "default_model": "deepseek-ai/DeepSeek-V2",
        "free_note": "硅基流动提供部分模型免费/低价调用。"
                       "注册地址: https://siliconflow.cn/",
    },
    "自定义配置": {
        "base_url": None,   # 用户需自行填入
        "api_key_placeholder": "请输入自定义 API Key",
        "models": [],        # 用户自行输入
        "default_model": "gpt-3.5-turbo",
        "free_note": "自行填入任意兼容 OpenAI 协议的 API 地址与 Key。",
    },
    "模拟数据演示": {
        "base_url": None,
        "api_key_placeholder": "",
        "models": [],
        "default_model": "",
        "free_note": "无需 API Key，使用内置 3 家模拟供应商数据演示全部功能。",
    },
}

# ---- 行业预警规则 ----
BRIGHTNESS_WARNING_THRESHOLD = 400  # 亮度低于此值触发低亮预警（cd/m²）
MEMORY_WARNING_THRESHOLD_GB = 4     # 内存低于此值触发卡顿风险（GB）

# ---- 目标市场 → 必须认证映射 ----
MARKET_CERTIFICATION_MAP: Dict[str, List[str]] = {
    "中东": ["CE", "SASO"],
    "欧洲": ["CE", "RoHS"],
    "北美": ["FCC", "UL"],
    "中国": ["CCC"],
    "东南亚": ["CE"],
    "不限": [],
}

# ---- 模拟数据（当用户未配置 API Key 时使用） ----
MOCK_SUPPLIER_DATA: List[Dict[str, str]] = [
    {
        "厂家名称": "MaxTouch Technology Co., Ltd.",
        "屏幕尺寸": "75\"",
        "亮度(cd/m²)": "350 cd/m²",
        "触控技术": "红外触控",
        "安卓版本": "Android 12",
        "CPU型号": "RK3588",
        "内存/存储": "4GB+32GB",
        "是否含OPS": "选配",
        "认证信息": "CE, FCC, RoHS",
    },
    {
        "厂家名称": "BrightVision Inc.",
        "屏幕尺寸": "86\"",
        "亮度(cd/m²)": "450 cd/m²",
        "触控技术": "电容触控",
        "安卓版本": "Android 13",
        "CPU型号": "Amlogic T982",
        "内存/存储": "8GB+128GB",
        "是否含OPS": "是",
        "认证信息": "CE, FCC, RoHS, SASO",
    },
    {
        "厂家名称": "EduSmart Displays Ltd.",
        "屏幕尺寸": "65\"",
        "亮度(cd/m²)": "300 cd/m²",
        "触控技术": "红外触控",
        "安卓版本": "Android 11",
        "CPU型号": "MTK 9950",
        "内存/存储": "2GB+16GB",
        "是否含OPS": "否",
        "认证信息": "CE",
    },
]


# ============================================================
# PDF 解析模块
# ============================================================

def extract_text_from_pdf(pdf_bytes: bytes) -> Optional[str]:
    """
    使用 pdfplumber 从 PDF 字节流中提取全部文本。

    Args:
        pdf_bytes: PDF 文件的字节流内容。

    Returns:
        提取到的文本字符串；如果解析失败则返回 None。
    """
    try:
        text_parts: List[str] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        full_text = "\n".join(text_parts).strip()
        if not full_text:
            logger.warning("PDF 文件中未提取到任何文本内容（可能为图片型 PDF）。")
            return None
        logger.info(f"PDF 文本提取成功，共 {len(full_text)} 字符。")
        return full_text
    except Exception as e:
        logger.error(f"PDF 解析失败: {e}")
        return None


# ============================================================
# AI / LLM 交互模块
# ============================================================

def _build_llm_prompt(pdf_text: str) -> str:
    """
    构建发送给 LLM 的提示词，指导其从 PDF 文本中提取结构化字段。

    Args:
        pdf_text: 从 PDF 中提取的原始文本。

    Returns:
        完整的 prompt 字符串。
    """
    fields_desc = "\n".join(
        [f"- {key}: {desc}" for key, desc in EXTRACTION_FIELDS.items()]
    )
    prompt = f"""你是一位专业的电子产品规格分析专家。请从以下电子白板（Interactive Flat Panel）的产品规格书文本中，提取指定的关键参数。

【提取字段说明】
{fields_desc}

【提取规则】
1. 如果某个字段在文本中未找到，请返回 "未提供"。
2. 亮度请提取数值及单位，如 "350 cd/m²"。
3. 屏幕尺寸请保留原样，如 "75\""。
4. 内存/存储请保留格式，如 "4GB+32GB"。
5. 认证信息请以逗号分隔列出，如 "CE, FCC, RoHS"。
6. 只返回一个合法的 JSON 对象，不要包含任何其他说明文字或 Markdown 代码块标记。

【PDF 文本内容】
{pdf_text[:8000]}

请严格按如下 JSON 格式返回（键名必须完全相同）：
{{"厂家名称": "...", "屏幕尺寸": "...", "亮度(cd/m²)": "...", "触控技术": "...", "安卓版本": "...", "CPU型号": "...", "内存/存储": "...", "是否含OPS": "...", "认证信息": "..."}}
"""
    return prompt


def call_llm_for_extraction(
    pdf_text: str,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: str = "gpt-3.5-turbo",
    temperature: float = 0.0,
    max_tokens: int = 512,
) -> Dict[str, str]:
    """
    调用 OpenAI 兼容 API 对 PDF 文本进行语义提取。

    Args:
        pdf_text: PDF 原始文本。
        api_base: API 地址（支持自定义代理地址）。
        api_key: API 密钥。
        model_name: 模型名称。
        temperature: 生成温度。
        max_tokens: 最大输出 token 数。

    Returns:
        提取后的字段字典；如果调用失败，返回默认值字典。
    """
    try:
        client = OpenAI(base_url=api_base, api_key=api_key)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个精确的电子白板规格信息提取器，只返回 JSON。",
                },
                {"role": "user", "content": _build_llm_prompt(pdf_text)},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        raw_output = response.choices[0].message.content.strip()
        # ---- 清理可能的 Markdown 代码块标记 ----
        if raw_output.startswith("```"):
            lines = raw_output.split("\n")
            # 去掉首行 ```json 和末行 ```
            lines = [l for l in lines if not l.strip().startswith("```")]
            raw_output = "\n".join(lines)

        extracted: Dict[str, str] = json.loads(raw_output)
        # ---- 确保所有字段都存在，缺失的用默认值填充 ----
        result: Dict[str, str] = {}
        for field in EXTRACTION_FIELDS:
            result[field] = extracted.get(field, DEFAULT_VALUES[field])
        logger.info("AI 字段提取成功。")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"AI 返回内容无法解析为 JSON: {e}，内容: {raw_output[:200]}")
        return dict(DEFAULT_VALUES)
    except Exception as e:
        logger.error(f"AI API 调用失败: {e}")
        return dict(DEFAULT_VALUES)


# ============================================================
# 行业规则预警模块
# ============================================================

def parse_numeric_value(text: str) -> Optional[float]:
    """
    从文本中解析出数值部分，用于规则检测。
    例如: "350 cd/m²" → 350.0, "4GB+32GB" 返回第一个数值 4.0。

    Args:
        text: 包含数值的字符串。

    Returns:
        解析出的浮点数；如果无法解析则返回 None。
    """
    import re

    matches = re.findall(r"(\d+\.?\d*)", str(text))
    if not matches:
        return None
    try:
        return float(matches[0])
    except ValueError:
        return None


def check_warnings(
    record: Dict[str, str], target_market: str = "不限"
) -> List[Dict[str, str]]:
    """
    根据行业规则对单条供应商记录进行预警检测。

    Args:
        record: 单条供应商字段字典。
        target_market: 目标市场（如 "中东", "欧洲"）。

    Returns:
        预警信息列表，每项包含 {"级别": "严重/提醒", "类型": "...", "详情": "..."}。
    """
    warnings: List[Dict[str, str]] = []

    # ---- 1. 亮度检测 ----
    brightness_str = record.get("亮度(cd/m²)", "")
    brightness = parse_numeric_value(brightness_str)
    if brightness is not None and brightness < BRIGHTNESS_WARNING_THRESHOLD:
        warnings.append(
            {
                "级别": "严重",
                "类型": "低亮预警",
                "详情": f'亮度为 {brightness_str}，低于行业推荐标准 400 cd/m²，室内展示效果可能不佳。',
            }
        )

    # ---- 2. 内存检测（取第一个数字作为内存容量） ----
    memory_str = record.get("内存/存储", "")
    memory_gb = parse_numeric_value(memory_str)
    if memory_gb is not None and memory_gb < MEMORY_WARNING_THRESHOLD_GB:
        warnings.append(
            {
                "级别": "严重",
                "类型": "卡顿风险",
                "详情": f'内存为 {memory_str}（RAM < {MEMORY_WARNING_THRESHOLD_GB}GB），多任务运行时可能出现卡顿。',
            }
        )

    # ---- 3. 目标市场认证检测 ----
    required_certs = MARKET_CERTIFICATION_MAP.get(target_market, [])
    cert_text = record.get("认证信息", "")
    cert_text_upper = cert_text.upper() if cert_text else ""
    for cert in required_certs:
        if cert.upper() not in cert_text_upper:
            warnings.append(
                {
                    "级别": "提醒",
                    "类型": "认证缺失",
                    "详情": f'目标市场 "{target_market}" 要求具备 {cert} 认证，当前规格书中未检测到该认证信息。',
                }
            )

    if not warnings:
        warnings.append({"级别": "正常", "类型": "无预警", "详情": "各项指标均在正常范围内。"})

    return warnings


# ============================================================
# 模拟数据模块
# ============================================================

def get_mock_analysis_results() -> pd.DataFrame:
    """
    返回模拟分析结果 DataFrame，供无 API Key 时演示使用。
    包含完整的字段数据和预警信息列。

    Returns:
        pandas DataFrame 包含供应商对比数据。
    """
    records: List[Dict[str, Any]] = []
    for data in MOCK_SUPPLIER_DATA:
        record = dict(data)
        warnings = check_warnings(record, target_market="不限")
        record["预警信息"] = "; ".join([f"[{w['类型']}]{w['详情']}" for w in warnings])
        records.append(record)
    df = pd.DataFrame(records)
    # 重新排序列，把预警信息放在最后
    col_order = list(EXTRACTION_FIELDS.keys()) + ["预警信息"]
    df = df[col_order]
    return df


# ============================================================
# 数据导出模块
# ============================================================

def export_to_excel(df: pd.DataFrame) -> bytes:
    """
    将 DataFrame 导出为 Excel 文件的字节流。

    Args:
        df: 供应商对比数据 DataFrame。

    Returns:
        Excel 文件的字节内容。
    """
    try:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="供应商对比")
        output.seek(0)
        logger.info("Excel 导出成功。")
        return output.getvalue()
    except Exception as e:
        logger.error(f"Excel 导出失败: {e}")
        raise


def export_to_csv(df: pd.DataFrame) -> bytes:
    """
    将 DataFrame 导出为 CSV 文件的字节流（UTF-8 BOM 编码，Excel 友好）。

    Args:
        df: 供应商对比数据 DataFrame。

    Returns:
        CSV 文件的字节内容。
    """
    try:
        output = io.BytesIO()
        # 写入 UTF-8 BOM，确保 Excel 正确识别中文
        output.write("\ufeff".encode("utf-8"))
        df.to_csv(output, index=False, encoding="utf-8")
        output.seek(0)
        logger.info("CSV 导出成功。")
        return output.getvalue()
    except Exception as e:
        logger.error(f"CSV 导出失败: {e}")
        raise


# ============================================================
# 主处理流程（供 app.py 调用）
# ============================================================

def process_pdf_files(
    pdf_files: List[bytes],
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: str = "gpt-3.5-turbo",
    temperature: float = 0.0,
    target_market: str = "不限",
    use_mock: bool = False,
) -> pd.DataFrame:
    """
    批量处理 PDF 文件，依次执行: PDF 文本提取 → AI 字段提取 → 预警检测 → 汇总成 DataFrame。

    Args:
        pdf_files: PDF 文件字节流列表。
        api_base: API 基础地址。
        api_key: API 密钥。
        model_name: 模型名称。
        temperature: 生成温度。
        target_market: 目标市场（用于认证预警）。
        use_mock: 是否强制使用模拟数据（API Key 未配置时自动启用）。

    Returns:
        包含所有供应商对比数据的 pandas DataFrame。
    """
    # ---- 判断是否需要使用模拟数据 ----
    if use_mock or not api_key:
        logger.info("未配置 API Key，使用模拟数据进行演示。")
        # 模拟延迟效果，让用户感知处理过程
        import time

        time.sleep(0.5)
        df = get_mock_analysis_results()
        # 根据目标市场重新计算预警
        for idx in range(len(df)):
            record = dict(df.iloc[idx])
            warnings = check_warnings(record, target_market=target_market)
            df.at[idx, "预警信息"] = "; ".join(
                [f"[{w['类型']}]{w['详情']}" for w in warnings]
            )
        return df

    # ---- 真实处理流程 ----
    all_records: List[Dict[str, Any]] = []

    for i, pdf_bytes in enumerate(pdf_files):
        logger.info(f"正在处理第 {i+1}/{len(pdf_files)} 个 PDF 文件...")

        # Step 1: 提取文本
        pdf_text = extract_text_from_pdf(pdf_bytes)
        if not pdf_text:
            # PDF 解析失败时使用默认值，保证不崩溃
            record = dict(DEFAULT_VALUES)
            record["厂家名称"] = f"PDF-{i+1}（解析失败）"
        else:
            # Step 2: AI 字段提取
            record = call_llm_for_extraction(
                pdf_text=pdf_text,
                api_base=api_base,
                api_key=api_key,
                model_name=model_name,
                temperature=temperature,
            )

        # Step 3: 预警检测
        warnings = check_warnings(record, target_market=target_market)
        record["预警信息"] = "; ".join(
            [f"[{w['类型']}]{w['详情']}" for w in warnings]
        )

        all_records.append(record)

    # Step 4: 构建 DataFrame
    df = pd.DataFrame(all_records)
    col_order = list(EXTRACTION_FIELDS.keys()) + ["预警信息"]
    df = df[col_order]
    logger.info(f"全部 {len(pdf_files)} 个文件处理完成。")
    return df