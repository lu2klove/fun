import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
from google.cloud import firestore
from google.oauth2 import service_account
import json

# --- 1. 페이지 설정 ---
st.set_page_config(
    page_title="Global Financial Dashboard",
    page_icon="📈",
    layout="wide"
)

# --- 2. Firestore 데이터베이스 초기화 ---
@st.cache_resource
def init_db():
    try:
        if "firebase" in st.secrets:
            key_dict = json.loads(st.secrets["firebase"]["text_key"])
            creds = service_account.Credentials.from_service_account_info(key_dict)
            return firestore.Client(credentials=creds, project=key_dict['project_id'])
        return None
    except Exception:
        return None

db = init_db()
COLLECTION_NAME = "my_portfolio"

# --- 3. DB 핸들링 함수 ---
def get_portfolio_from_db():
    if db is None: return []
    try:
        docs = db.collection(COLLECTION_NAME).order_by("created_at").stream()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception:
        return []

def add_to_portfolio(name, ticker, buy_price, quantity):
    if db:
        db.collection(COLLECTION_NAME).add({
            "name": name, 
            "ticker": ticker, 
            "buy_price": buy_price,
            "quantity": quantity, 
            "created_at": datetime.now()
        })
        return True
    return False

def delete_from_portfolio(doc_id):
    if db:
        db.collection(COLLECTION_NAME).document(doc_id).delete()
        return True
    return False

# --- 4. 데이터 수집 함수 ---
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
            df.index = df.index.strftime('%H:%M' if period == "1d" else '%Y-%m-%d')
            return df
    except Exception:
        pass
    return pd.DataFrame()

# --- 5. 회사명-티커 변환 맵핑 ---
COMPANY_TICKER_MAP = {
    "삼성전자": "005930.KS", "SK하이닉스": "000660.KS", "네이버": "035420.KS",
    "카카오": "035720.KS", "현대차": "005380.KS", "애플": "AAPL", "테슬라": "TSLA",
    "엔비디아": "NVDA", "비트코인": "BTC-USD"
}

def get_ticker_from_name(name):
    clean = name.strip().replace(" ", "")
    return COMPANY_TICKER_MAP.get(clean, clean.upper())

# --- 6. UI 구성 ---
st.title("📊 실시간 글로벌 경제 지표 대시보드")
st.caption(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# 1. 증시 비교 섹션
col_left, col_right = st.columns(2)
period_map = {"1일": "1d", "1개월": "1mo", "1년": "1y"}

with col_left:
    st.subheader("🇰🇷 국내 증시")
    k_p = st.radio("기간 (국내)", ["1일", "1개월", "1년"], index=1, horizontal=True, key="k_p")
    p1, _, pct1 = get_finance_data("^KS11")
    p2, _, pct2 = get_finance_data("^KQ11")
    c1, c2 = st.columns(2)
    c1.metric("KOSPI", f"{p1:,.2f}", f"{pct1:+.2f}%")
    c2.metric("KOSDAQ", f"{p2:,.2f}", f"{pct2:+.2f}%")
    df = get_chart_data("^KS11", "KOSPI", period_map[k_p])
    if not df.empty: st.line_chart(df)

with col_right:
    st.subheader("🇺🇸 미국 증시")
    u_p = st.radio("기간 (미국)", ["1일", "1개월", "1년"], index=1, horizontal=True, key="u_p")
    p1, _, pct1 = get_finance_data("^GSPC")
    p2, _, pct2 = get_finance_data("^IXIC")
    c1, c2 = st.columns(2)
    c1.metric("S&P 500", f"{p1:,.2f}", f"{pct1:+.2f}%")
    c2.metric("NASDAQ", f"{p2:,.2f}", f"{pct2:+.2f}%")
    df = get_chart_data("^IXIC", "NASDAQ", period_map[u_p])
    if not df.empty: st.line_chart(df)

st.divider()

# 2. 보유 종목 포트폴리오 관리
st.subheader("💼 내 보유 종목 포트폴리오 관리")

with st.expander("➕ 새 종목 등록하기", expanded=False):
    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
    in_name = c1.text_input("종목명 (또는 티커)")
    in_buy = c2.number_input("평단가", min_value=0.0, step=100.0)
    in_qty = c3.number_input("수량", min_value=0, step=1)
    # 버튼 클릭 시 즉시 로직 실행 후 rerun 호출
    if c4.button("등록"):
        if in_name and in_buy > 0:
            if add_to_portfolio(in_name, get_ticker_from_name(in_name), in_buy, in_qty):
                st.success(f"{in_name} 등록 완료!")
                st.rerun()

portfolio = get_portfolio_from_db()
if portfolio:
    data_list = []
    total_cost, total_eval = 0, 0
    
    for item in portfolio:
        curr, _, _ = get_finance_data(item['ticker'])
        cost = item['buy_price'] * item['quantity']
        eval_v = curr * item['quantity']
        total_cost += cost
        total_eval += eval_v
        
        gain = eval_v - cost
        gain_pct = (gain / cost * 100) if cost > 0 else 0
        
        data_list.append({
            "종목": item['name'],
            "티커": item['ticker'],
            "수량": item['quantity'],
            "평단가": f"{item['buy_price']:,.0f}",
            "현재가": f"{curr:,.0f}",
            "수익금": f"{gain:,.0f}",
            "수익률": f"{gain_pct:+.2f}%",
            "ID": item['id']
        })

    # 전체 요약 지표
    s1, s2, s3 = st.columns(3)
    s1.metric("총 매수금액", f"{total_cost:,.0f}원")
    s2.metric("총 평가금액", f"{total_eval:,.0f}원")
    total_gain_pct = (total_eval / total_cost - 1) * 100 if total_cost > 0 else 0
    s3.metric("총 손익", f"{total_eval-total_cost:,.0f}원", f"{total_gain_pct:+.2f}%")

    # 포트폴리오 테이블
    df_p = pd.DataFrame(data_list)
    st.dataframe(df_p.drop(columns="ID"), use_container_width=True)

    # 삭제 기능
    del_col1, del_col2 = st.columns([3, 1])
    target = del_col1.selectbox("삭제할 종목 선택", df_p['종목'].tolist())
    if del_col2.button("선택 삭제"):
        doc_id = df_p[df_p['종목'] == target]['ID'].values[0]
        if delete_from_portfolio(doc_id):
            st.rerun()
else:
    st.info("등록된 종목이 없습니다. 위 '새 종목 등록하기'를 이용해 보세요.")

st.divider()

# 3. 종목 계산기 및 상세 분석
st.subheader("🧮 종목 계산기 & 🔍 상세 분석")
calc_col1, calc_col2 = st.columns([1, 2])

with calc_col1:
    st.write("📌 **계산기 입력**")
    calc_name = st.text_input("분석할 종목명", placeholder="예: 삼성전자")
    c_price = 0.0
    if calc_name:
        c_ticker = get_ticker_from_name(calc_name)
        c_price, _, _ = get_finance_data(c_ticker)
        st.info(f"현재 시세: {c_price:,.2f}")

    b_price = st.number_input("구매 가격", value=float(c_price) if c_price > 0 else 0.0)
    qty = st.number_input("보유 수량 ", value=0)
    
    # 목표 비율
    p_c1, p_c2 = st.columns(2)
    sl_pct = p_c1.number_input("손절 (%)", value=10.0)
    tp_pct = p_c2.number_input("익절 (%)", value=20.0)

with calc_col2:
    if b_price > 0 and qty > 0:
        total_inv = b_price * qty
        sl_price = b_price * (1 - sl_pct/100)
        tp_price = b_price * (1 + tp_pct/100)
        
        st.write(f"💰 **투자 요약: {total_inv:,.0f}원**")
        g1, g2 = st.columns(2)
        g1.error(f"📉 손절가: {sl_price:,.0f}")
        g2.success(f"📈 익절가: {tp_price:,.0f}")
        
        # 상세 펀더멘탈 (yf.info 활용)
        if calc_name:
            st.write("---")
            st.write(f"🔍 **{calc_name} 주요 지표**")
            stock_info = yf.Ticker(get_ticker_from_name(calc_name)).info
            f1, f2, f3 = st.columns(3)
            f1.metric("PER", f"{stock_info.get('trailingPE', 'N/A')}")
            f2.metric("PBR", f"{stock_info.get('priceToBook', 'N/A')}")
            f3.metric("배당수익률", f"{stock_info.get('dividendYield', 0)*100:.2f}%" if stock_info.get('dividendYield') else "0%")
    else:
        st.info("종목명과 투자 정보를 입력하면 가이드와 상세 지표가 표시됩니다.")

# 사이드바
# on_click 콜백 대신 버튼 클릭을 직접 확인하여 rerun 호출
if st.sidebar.button("새로고침"):
    st.rerun()
st.sidebar.info("Firestore DB에 안전하게 저장됩니다.")
