import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime

# --- 페이지 설정 ---
st.set_page_config(
    page_title="Global Financial Dashboard",
    page_icon="📈",
    layout="wide" # 화면을 넓게 사용하기 위해 wide 모드 설정
)

# --- 타이틀 ---
st.title("📊 실시간 글로벌 경제 지표 대시보드")
# 현재 일시 기준 업데이트 표시
st.caption(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# --- 회사명-티커 변환 맵핑 사전 ---
COMPANY_TICKER_MAP = {
    "삼성전자": "005930.KS",
    "SK하이닉스": "000660.KS",
    "네이버": "035420.KS",
    "카카오": "035720.KS",
    "현대차": "005380.KS",
    "LG에너지솔루션": "373220.KS",
    "애플": "AAPL",
    "테슬라": "TSLA",
    "엔비디아": "NVDA",
    "마이크로소프트": "MSFT",
    "구글": "GOOGL",
    "아마존": "AMZN",
    "넷플릭스": "NFLX",
    "메타": "META",
    "비트코인": "BTC-USD"
}

# --- 데이터 가져오기 함수 ---
@st.cache_data(ttl=60)
def get_finance_data(ticker):
    try:
        yt = yf.Ticker(ticker)
        data = yt.history(period="1d")
        if not data.empty:
            price = data['Close'].iloc[-1]
            prev_price = data['Open'].iloc[-1]
            change = price - prev_price
            change_pct = (change / prev_price) * 100
            return price, change, change_pct
    except Exception:
        return 0.0, 0.0, 0.0

@st.cache_data(ttl=300)
def get_chart_data(ticker, name, period="1mo"):
    try:
        yt = yf.Ticker(ticker)
        interval = "15m" if period == "1d" else "1d"
        data = yt.history(period=period, interval=interval)
        
        if not data.empty:
            df = data[['Close']].copy()
            df.columns = [name]
            if period == "1d":
                df.index = df.index.strftime('%H:%M')
            else:
                df.index = df.index.strftime('%Y-%m-%d')
            return df
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

def get_ticker_from_name(name):
    clean_name = name.strip().replace(" ", "")
    if clean_name in COMPANY_TICKER_MAP:
        return COMPANY_TICKER_MAP[clean_name]
    return clean_name.upper()

# --- 화면 구성 ---

# 1. 상단: 국내/미국 증시 비교
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("🇰🇷 국내 증시 흐름 비교")
    k_period = st.radio("기간 선택 (국내)", ["1일", "1개월", "1년"], index=1, horizontal=True, key="k_period_btn")
    period_map = {"1일": "1d", "1개월": "1mo", "1년": "1y"}
    selected_k_period = period_map[k_period]

    k_col1, k_col2 = st.columns(2)
    kp_price, kp_chg, kp_pct = get_finance_data("^KS11")
    kd_price, kd_chg, kd_pct = get_finance_data("^KQ11")
    
    k_col1.metric("KOSPI", f"{kp_price:,.2f}", f"{kp_pct:+.2f}%")
    k_col2.metric("KOSDAQ", f"{kd_price:,.2f}", f"{kd_pct:+.2f}%")
    
    kp_df = get_chart_data("^KS11", "KOSPI", period=selected_k_period)
    kd_df = get_chart_data("^KQ11", "KOSDAQ", period=selected_k_period)
    
    if not kp_df.empty and not kd_df.empty:
        k_combined = pd.concat([kp_df, kd_df], axis=1)
        k_combined = k_combined[["KOSPI", "KOSDAQ"]]
        st.line_chart(k_combined, color=["#0000FF", "#FF0000"])

with col_right:
    st.subheader("🇺🇸 미국 증시 흐름 비교")
    u_period = st.radio("기간 선택 (미국)", ["1일", "1개월", "1년"], index=1, horizontal=True, key="u_period_btn")
    selected_u_period = period_map[u_period]

    u_col1, u_col2 = st.columns(2)
    sp_price, sp_chg, sp_pct = get_finance_data("^GSPC")
    nas_price, nas_chg, nas_pct = get_finance_data("^IXIC")
    
    u_col1.metric("S&P 500", f"{sp_price:,.2f}", f"{sp_pct:+.2f}%")
    u_col2.metric("NASDAQ", f"{nas_price:,.2f}", f"{nas_pct:+.2f}%")
    
    sp_df = get_chart_data("^GSPC", "S&P 500", period=selected_u_period)
    nas_df = get_chart_data("^IXIC", "NASDAQ", period=selected_u_period)
    
    if not sp_df.empty and not nas_df.empty:
        u_combined = pd.concat([sp_df, nas_df], axis=1)
        u_combined = u_combined[["NASDAQ", "S&P 500"]]
        st.line_chart(u_combined, color=["#0000FF", "#FF0000"])

st.divider()

# 2. 중간: 경제 지표 분석
st.subheader("🌐 주요 경제 지표 분석")
eco_period_label = st.radio("지표 조회 기간", ["1일", "1개월", "1년"], index=1, horizontal=True, key="eco_period_btn")
selected_eco_period = period_map[eco_period_label]

col_bot1, col_bot2, col_bot3, col_bot4 = st.columns(4)

with col_bot1:
    st.write("💱 **환율 (USD/KRW)**")
    fx_price, fx_chg, fx_pct = get_finance_data("KRW=X")
    st.metric("원/달러 환율", f"{fx_price:,.2f}원", f"{fx_chg:+.2f}")
    if fx_price <= 1500: st.success("✅ 정상 (1500원 이하)")
    else: st.error("⚠️ 주의 (1500원 초과)")
    fx_chart = get_chart_data("KRW=X", "USD/KRW", period=selected_eco_period)
    if not fx_chart.empty: st.line_chart(fx_chart, height=150)

with col_bot2:
    st.write("🛢️ **에너지 (WTI Oil)**")
    oil_price, oil_chg, oil_pct = get_finance_data("CL=F")
    st.metric("WTI 유가", f"${oil_price:,.2f}", f"{oil_pct:+.2f}%")
    if oil_price <= 100: st.success("✅ 정상 ($100 이하)")
    else: st.error("⚠️ 주의 ($100 초과)")
    oil_chart = get_chart_data("CL=F", "WTI", period=selected_eco_period)
    if not oil_chart.empty: st.line_chart(oil_chart, height=150)

with col_bot3:
    st.write("🟡 **금 (Gold)**")
    gold_price, gold_chg, gold_pct = get_finance_data("GC=F")
    st.metric("금 선물", f"${gold_price:,.2f}", f"{gold_pct:+.2f}%")
    gold_chart = get_chart_data("GC=F", "Gold", period=selected_eco_period)
    if not gold_chart.empty: st.line_chart(gold_chart, height=150, color="#FFD700")

with col_bot4:
    st.write("⚪ **은 (Silver)**")
    silver_price, silver_chg, silver_pct = get_finance_data("SI=F")
    st.metric("은 선물", f"${silver_price:,.2f}", f"{silver_pct:+.2f}%")
    silver_chart = get_chart_data("SI=F", "Silver", period=selected_eco_period)
    if not silver_chart.empty: st.line_chart(silver_chart, height=150, color="#C0C0C0")

st.divider()

# 3. 하단: 관심 종목 분석
st.subheader("⭐ 관심 종목 분석")
item_period_label = st.select_slider("종목 차트 기간 설정", options=["1일", "1개월", "1년"], value="1개월")
selected_item_period = period_map[item_period_label]

input_cols = st.columns(5)
watchlist_data = []

for i in range(5):
    name_input = input_cols[i].text_input(f"종목 {i+1}", key=f"ticker_{i}")
    if name_input:
        ticker = get_ticker_from_name(name_input)
        watchlist_data.append({"name": name_input, "ticker": ticker})

if watchlist_data:
    display_cols = st.columns(len(watchlist_data))
    for i, item in enumerate(watchlist_data):
        with display_cols[i]:
            price, chg, pct = get_finance_data(item["ticker"])
            if price != 0:
                st.metric(f"{item['name']} ({item['ticker']})", f"{price:,.2f}", f"{pct:+.2f}%")
                chart_data = get_chart_data(item["ticker"], item["name"], period=selected_item_period)
                if not chart_data.empty: st.line_chart(chart_data, height=150)
                else: st.warning("차트 데이터 없음")
            else: st.error(f"'{item['name']}' 검색 실패")

st.divider()

# 4. 섹션: 종목 계산기 (새로 추가된 기능)
st.subheader("🧮 종목 계산기 (수익/손실 가이드)")
calc_col1, calc_col2 = st.columns([1, 2])

with calc_col1:
    st.write("📌 **투자 정보 입력**")
    calc_name = st.text_input("계산할 종목명 또는 티커", placeholder="예: 삼성전자 또는 AAPL")
    
    current_price = 0.0
    if calc_name:
        calc_ticker = get_ticker_from_name(calc_name)
        current_price, _, _ = get_finance_data(calc_ticker)
        st.info(f"💡 현재 시세: **{current_price:,.2f}**")

    # 입력 폼
    buy_price = st.number_input("구매 가격 (1주당)", value=float(current_price) if current_price > 0 else 0.0, step=100.0)
    quantity = st.number_input("보유 수량", value=0, step=1)
    
    total_investment = buy_price * quantity
    st.write(f"💰 **총 투자 금액: {total_investment:,.2f}**")

with calc_col2:
    st.write("📊 **목표가 및 손절가 가이드**")
    if total_investment > 0:
        # 가이드 금액 계산
        stop_loss = buy_price * 0.9  # -10%
        target_1 = buy_price * 1.1   # +10%
        target_final = buy_price * 1.2 # +20%
        
        # UI 레이아웃
        guide_col1, guide_col2, guide_col3 = st.columns(3)
        
        with guide_col1:
            st.error("📉 **손절가 (-10%)**")
            st.subheader(f"{stop_loss:,.2f}")
            st.caption(f"예상 손실액: -{(total_investment * 0.1):,.2f}")

        with guide_col2:
            st.success("📈 **익절가 1 (+10%)**")
            st.subheader(f"{target_1:,.2f}")
            st.caption(f"예상 수익액: +{(total_investment * 0.1):,.2f}")

        with guide_col3:
            st.info("🚀 **최종 익절가 (+20%)**")
            st.subheader(f"{target_final:,.2f}")
            st.caption(f"예상 수익액: +{(total_investment * 0.2):,.2f}")
            
        st.divider()
        # 현재가 대비 현황 파악 (종목명이 있을 때만)
        if current_price > 0:
            profit_loss = (current_price - buy_price) * quantity
            profit_rate = ((current_price / buy_price) - 1) * 100 if buy_price > 0 else 0
            
            st.write(f"🔎 **현재 시세 기준 분석**")
            status_color = "red" if profit_loss < 0 else "blue"
            st.markdown(f"현재 수익금: <span style='color:{status_color}; font-weight:bold;'>{profit_loss:,.2f} ({profit_rate:+.2f}%)</span>", unsafe_allow_html=True)
    else:
        st.info("구매 가격과 보유 수량을 입력하면 계산기가 작동합니다.")

# 사이드바 설정
st.sidebar.header("Dashboard Settings")
if st.sidebar.button("새로고침"):
    st.rerun()

st.sidebar.divider()
st.sidebar.info("""
**계산기 활용 팁:**
- 종목명을 입력하면 실시간 현재가를 참고할 수 있습니다.
- '구매 가격'을 직접 수정하여 시나리오별 수익/손실을 계산해보세요.
- 손절가 및 익절가는 투자 원금(평단가) 기준으로 계산됩니다.
""")
