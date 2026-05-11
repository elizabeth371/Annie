# ============================================================
# 外贸采购比价助手 - 界面展示层 (app.py)
# 遵循 MVC 架构，本模块仅包含 Streamlit 界面代码
# 所有业务逻辑均调用 core.py 中的函数
# ============================================================

import streamlit as st
import pandas as pd
from datetime import datetime

# ---- 导入核心业务逻辑模块 ----
from core import (
    EXTRACTION_FIELDS,
    MARKET_CERTIFICATION_MAP,
    export_to_csv,
    export_to_excel,
    process_pdf_files,
    get_mock_analysis_results,
)

# ===================== 页面配置 =====================
st.set_page_config(
    page_title="外贸采购比价助手 - Sourcing Agent",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ===================== 自定义 CSS（含移动端适配） =====================
st.markdown(
    """
<style>
/* ---- 全局字体与间距 ---- */
html, body, [class*="css"] {
    font-family: "Microsoft YaHei", "PingFang SC", "Helvetica Neue", Arial, sans-serif;
}
/* ---- 表格内预警高亮 ---- */
.warning-severe {
    color: #D32F2F;
    font-weight: bold;
    background-color: #FFEBEE;
    padding: 2px 6px;
    border-radius: 4px;
}
.warning-reminder {
    color: #F57C00;
    font-weight: bold;
    background-color: #FFF3E0;
    padding: 2px 6px;
    border-radius: 4px;
}
/* ---- 移动端适配 ---- */
@media (max-width: 768px) {
    .stApp {
        padding: 0.5rem;
    }
    h1 {
        font-size: 1.5rem !important;
    }
    div[data-testid="stDataFrame"] {
        font-size: 12px;
    }
}
/* ---- PWA 相关的 viewport 声明通过 Streamlit 配置自动生成，此处保留自定义 ---- */
</style>
""",
    unsafe_allow_html=True,
)

# ===================== 侧边栏：设置面板 =====================
with st.sidebar:
    st.title("⚙️ 设置面板")

    # ---- API 配置 ----
    st.subheader("🔑 API 配置")
    api_base = st.text_input(
        "API Base URL",
        value="https://api.openai.com/v1",
        help="支持任意 OpenAI 兼容 API 地址（如 OpenRouter、本地 Ollama 等）。",
        placeholder="https://api.openai.com/v1",
    )
    api_key = st.text_input(
        "API Key",
        type="password",
        placeholder="sk-xxxxxxxxxxxxxxxx",
        help="输入您的 OpenAI API Key 或代理服务的 Key。留空则自动使用模拟数据演示。",
    )

    # ---- 模型参数 ----
    st.subheader("🤖 模型参数")
    model_name = st.selectbox(
        "模型名称",
        options=["gpt-3.5-turbo", "gpt-4", "gpt-4-turbo", "gpt-4o", "gpt-4o-mini"],
        index=0,
        help="选择用于信息提取的大语言模型。",
    )
    temperature = st.slider(
        "Temperature",
        min_value=0.0,
        max_value=1.0,
        value=0.0,
        step=0.1,
        help="0 = 确定性输出（推荐用于数据提取），1 = 随机性输出。",
    )

    # ---- 目标市场选择（影响认证预警） ----
    st.subheader("🌍 目标市场")
    target_market = st.selectbox(
        "选择出口目标市场",
        options=list(MARKET_CERTIFICATION_MAP.keys()),
        index=0,
        help="根据目标市场检测必要的产品认证（如 CE、SASO、FCC 等）。",
    )

    # ---- 分隔线 ---- 
    st.divider()

    # ---- 模拟演示开关 ----
    st.subheader("🧪 演示模式")
    use_mock = st.checkbox(
        "强制使用模拟数据",
        value=not bool(api_key),
        help="勾选后将忽略 API Key，使用内置的 3 家模拟供应商数据进行演示。",
    )

    # ---- 使用提示 ----
    st.divider()
    st.markdown(
        """
        **📋 使用步骤：**
        1. 上传多个 PDF 规格书
        2. （可选）配置 API Key
        3. 选择目标市场
        4. 点击「开始分析」
        5. 对比结果 & 下载报表
        """
    )
    st.caption(f"© 2026 Sourcing Agent v1.0 | 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# ===================== 主页面 =====================

# ---- 标题区 ----
st.title("📊 外贸采购比价助手")
st.markdown("**Sourcing Agent** —— 智能解析电子白板 PDF 规格书，自动对比供应商关键参数，生成预警报告。")

# ---- 文件上传区 ----
st.subheader("📄 上传 PDF 规格书")
uploaded_files = st.file_uploader(
    "支持拖拽上传多个 PDF 文件",
    type=["pdf"],
    accept_multiple_files=True,
    help="拖拽或点击上传多家供应商的电子白板规格书 PDF。",
)

# ---- 操作按钮 ----
col1, col2 = st.columns([1, 4])
with col1:
    analyze_btn = st.button(
        "🔍 开始分析",
        type="primary",
        use_container_width=True,
        disabled=len(uploaded_files or []) == 0,
    )

# ---- 初始化 session_state ----
if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None
    st.session_state.processed_files_count = 0

# ---- 执行分析 ----
if analyze_btn and uploaded_files:
    # 读取所有 PDF 文件的字节流
    pdf_bytes_list = []
    for f in uploaded_files:
        pdf_bytes_list.append(f.read())

    with st.spinner(f"正在分析 {len(uploaded_files)} 份规格书，请稍候..."):
        try:
            df_result = process_pdf_files(
                pdf_files=pdf_bytes_list,
                api_base=api_base if api_base else "https://api.openai.com/v1",
                api_key=api_key,
                model_name=model_name,
                temperature=temperature,
                target_market=target_market,
                use_mock=use_mock or not api_key,
            )
            st.session_state.analysis_result = df_result
            st.session_state.processed_files_count = len(uploaded_files)
            st.success(f"✅ 分析完成！共处理 {len(uploaded_files)} 份规格书。")
        except Exception as e:
            st.error(f"❌ 分析过程出错: {str(e)}")
            st.session_state.analysis_result = None

# ===================== 结果展示区 =====================

if st.session_state.analysis_result is not None:
    df = st.session_state.analysis_result

    st.divider()
    st.subheader("📋 供应商对比表格")

    # ---- 使用 st.dataframe 展示可交互表格，并对预警列进行颜色标注 ----
    # 将预警信息列中的严重/提醒进行视觉区分
    def color_warnings(val: str) -> str:
        """根据预警内容返回 CSS 类名。"""
        if not isinstance(val, str):
            return ""
        if "严重" in val or "低亮" in val or "卡顿" in val:
            return "background-color: #FFEBEE; color: #D32F2F; font-weight: bold;"
        elif "提醒" in val or "认证缺失" in val:
            return "background-color: #FFF3E0; color: #F57C00; font-weight: bold;"
        return ""

    # 使用列配置进行条件格式化
    column_config = {}
    for col in df.columns:
        if col == "预警信息":
            column_config[col] = st.column_config.TextColumn(
                "预警信息",
                help="红色 = 严重预警，橙色 = 提醒",
                width="large",
            )
        else:
            column_config[col] = st.column_config.TextColumn(col)

    st.dataframe(
        df.style.applymap(color_warnings, subset=["预警信息"]),
        use_container_width=True,
        height=min(400, 60 * len(df) + 60),
        column_config=column_config,
        hide_index=True,
    )

    # ---- 预警摘要 ----
    st.subheader("⚠️ 预警摘要")
    warning_col1, warning_col2, warning_col3 = st.columns(3)

    # 统计各类预警数量
    all_warnings_text = " ".join(df["预警信息"].tolist())
    severe_count = all_warnings_text.count("[严重")
    reminder_count = all_warnings_text.count("[提醒")
    normal_count = all_warnings_text.count("[正常")

    with warning_col1:
        st.metric("🔴 严重预警", severe_count)
    with warning_col2:
        st.metric("🟠 提醒事项", reminder_count)
    with warning_col3:
        st.metric("🟢 正常", normal_count)

    # ---- 详细预警列表 ----
    with st.expander("📋 查看详细预警信息", expanded=(severe_count > 0)):
        for idx, row in df.iterrows():
            supplier_name = row.get("厂家名称", f"供应商 {idx+1}")
            warning_text = row.get("预警信息", "")
            if warning_text:
                # 按分号分割各条预警
                warning_items = warning_text.split("; ")
                for item in warning_items:
                    if item.strip():
                        # 判断级别
                        if "[严重]" in item:
                            st.markdown(f"🔴 **{supplier_name}** → {item}")
                        elif "[提醒]" in item:
                            st.markdown(f"🟠 **{supplier_name}** → {item}")
                        elif "[正常]" in item:
                            st.markdown(f"🟢 **{supplier_name}** → {item}")

    # ---- 导出下载区 ----
    st.divider()
    st.subheader("📥 导出报表")

    export_col1, export_col2 = st.columns(2)

    with export_col1:
        try:
            excel_data = export_to_excel(df)
            st.download_button(
                label="⬇️ 下载 Excel 报表 (.xlsx)",
                data=excel_data,
                file_name=f"供应商对比报表_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Excel 导出失败: {e}")

    with export_col2:
        try:
            csv_data = export_to_csv(df)
            st.download_button(
                label="⬇️ 下载 CSV 报表 (.csv)",
                data=csv_data,
                file_name=f"供应商对比报表_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"CSV 导出失败: {e}")

    st.caption("💡 报表包含所有提取字段及预警信息，可直接用于采购决策汇报。")

else:
    # ---- 未分析时的引导提示 ----
    if not uploaded_files:
        st.info("👆 请先上传 PDF 规格书文件，然后点击「开始分析」按钮。")

        # ---- 展示功能预览 ----
        with st.expander("📖 功能介绍与使用说明", expanded=False):
            st.markdown(
                """
                ### 🎯 功能概述
                本工具专为**外贸电子白板（Interactive Flat Panel）采购**场景设计，可帮助您：
                
                **1. 自动解析 PDF 规格书**
                - 上传多家供应商的产品规格书 PDF
                - AI 自动提取屏幕尺寸、亮度、触控技术、CPU、内存等关键参数
                
                **2. 智能对比分析**
                - 以表格形式横向对比所有供应商的核心参数
                - 一目了然发现各家优劣
                
                **3. 行业规则预警**
                - 🔴 亮度 < 400 cd/m² → 低亮预警
                - 🔴 内存 < 4GB → 卡顿风险
                - 🟠 根据目标市场检测缺失认证（如中东需 CE+SASO）
                
                **4. 一键导出报表**
                - 支持 Excel (.xlsx) 和 CSV 格式下载
                - 包含完整数据和预警信息，可直接用于汇报
                
                ### 🔧 使用方式
                - **无 API Key**：自动使用内置模拟数据演示（3 家虚拟供应商）
                - **有 API Key**：真实解析您的 PDF 规格书
                - **自定义 API**：支持任何 OpenAI 兼容接口（如 OpenRouter、Ollama 等）
                """
            )

# ===================== 页脚 =====================
st.divider()
st.caption(
    "⚠️ 免责声明：本工具提供的分析结果仅供参考，最终采购决策请结合实物考察和合同条款。"
)