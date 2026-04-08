import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
import json

# --- 1. 페이지 설정 ---
st.set_page_config(
    page_title="Global Financial Dashboard",
    page_icon="📈",
    layout="wide"
)

# --- 2. 데이터베이스 초기화 (Mock/Firestore 구조) ---
# 실제 환경에서는 st.secrets["firebase"] 설정을 사용하세요.
@st.cache_resource
def init_db():
    try:
        from google.cloud import firestore
        from google.oauth2 import service_account
        if "firebase" in st.secrets:
            key_dict = json.loads(st.secrets["firebase"]["text_key"])
            creds = service_account.Credentials.from_service_account_info(key_dict)
            return firestore.Client(credentials=creds, project=key_dict['project_id'])
    except Exception as e:
        return None
    return None

db = init_db()
COLLECTION_NAME = "my_portfolio"
APP_ID = "stock-manager-v1"

# --- 3. DB 핸들링 함수 ---
def get_portfolio_from_db():
    if db is None:
        # DB 연결 실패 시 세션 스테이트를 임시 저장소로 활용
        if "temp_portfolio" not in st.session_state:
            st.session_state.temp_portfolio = []
        return st.session_state.temp_portfolio
    try:
        docs = db.collection("artifacts", APP_ID, "public", "data", COLLECTION_NAME).order_by("created_at").stream()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except:
        return []

def add_to_portfolio(name, ticker, buy_price, quantity):
    data = {
        "name": name, 
        "ticker": ticker, 
        "buy_price": float(buy_price),
        "quantity": int(quantity), 
        "created_at": datetime.now()
    }
    if db:
        db.collection("artifacts", APP_ID, "public", "data", COLLECTION_NAME).add(data)
    else:
        if "temp_portfolio" not in st.session_state: st.session_state.temp_portfolio = []
        data["id"] = str(len(st.session_state.temp_portfolio))
        st.session_state.temp_portfolio.append(data)

def delete_from_portfolio(doc_id):
    if db:
        db.collection("artifacts", APP_ID, "public", "data", COLLECTION_NAME).document(doc_id).delete()
    else:
        st.session_state.temp_portfolio = [item for item in st.session_state.temp_portfolio if item.get('id') != doc_id]

# --- 4. 데이터 수집 함수 ---
@st.cache_data(ttl=60)
def get_finance_data(ticker):
    try:
        yt = yf.Ticker(ticker)
        data = yt.history(period="2d")
        if len(data) >= 2:
            price = data['Close'].iloc[-1]
            prev_price = data['Close'].iloc[-2]
            change = price - prev_price
            return price, change, (change / prev_price) * 100
        elif not data.empty:
            price = data['Close'].iloc[-1]
            return price, 0.0, 0.0
    except:
        pass
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
            # 인덱스 포맷 변경
            if period == "1d":
                df.index = df.index.strftime('%H:%M')
            else:
                df.index = df.index.strftime('%Y-%m-%d')
            return df
    except:
        pass
    return pd.DataFrame()

COMPANY_TICKER_MAP = {
    "삼성전자": "005930.KS", "SK하이닉스": "000660.KS", "애플": "AAPL", "테슬라": "TSLA", "엔비디아": "NVDA"
}

def get_ticker_from_name(name):
    clean = name.strip().replace(" ", "")
    return COMPANY_TICKER_MAP.get(clean, clean.upper())

# --- 5. UI 구성 ---
st.title("📊 실시간 글로벌 경제 지표 대시보드")
st.caption(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# 지수 비교 섹션
st.divider()
col_left, col_right = st.columns(2)
period_map = {"1일": "1d", "1개월": "1mo", "1년": "1y"}

with col_left:
    st.subheader("🇰🇷 국내 증시")
    k_p_label = st.radio("기간 (국내)", ["1일", "1개월", "1년"], index=1, horizontal=True, key="k_period")
    
    m1, m2 = st.columns(2)
    p1, _, pct1 = get_finance_data("^KS11")
    p2, _, pct2 = get_finance_data("^KQ11")
    m1.metric("KOSPI", f"{p1:,.2f}", f"{pct1:+.2f}%")
    m2.metric("KOSDAQ", f"{p2:,.2f}", f"{pct2:+.2f}%")
    
    df_k = get_chart_data("^KS11", "KOSPI", period_map[k_p_label])
    if not df_k.empty: 
        st.line_chart(df_k)

with col_right:
    st.subheader("🇺🇸 미국 증시")
    u_p_label = st.radio("기간 (미국)", ["1일", "1개월", "1년"], index=1, horizontal=True, key="u_period")
    
    m3, m4 = st.columns(2)
    p3, _, pct3 = get_finance_data("^GSPC")
    p4, _, pct4 = get_finance_data("^IXIC")
    m3.metric("S&P 500", f"{p3:,.2f}", f"{pct3:+.2f}%")
    m4.metric("NASDAQ", f"{p4:,.2f}", f"{pct4:+.2f}%")
    
    df_u = get_chart_data("^IXIC", "NASDAQ", period_map[u_p_label])
    if not df_u.empty: 
        st.line_chart(df_u)

st.divider()

# 보유 종목 관리 섹션
st.subheader("💼 내 보유 종목 포트폴리오")

# 1. 입력창
with st.expander("➕ 새 종목 등록", expanded=True):
    with st.form("add_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([2, 2, 2])
        in_name = c1.text_input("종목명 (예: 삼성전자, AAPL)")
        in_buy = c2.number_input("평단가", min_value=0.0, step=100.0)
        in_qty = c3.number_input("수량", min_value=0, step=1)
        submit = st.form_submit_button("포트폴리오에 추가")
        
        if submit:
            if in_name and in_buy > 0 and in_qty > 0:
                ticker = get_ticker_from_name(in_name)
                add_to_portfolio(in_name, ticker, in_buy, in_qty)
                st.success(f"{in_name}({ticker}) 등록 완료!")
                st.rerun()
            else:
                st.error("모든 정보를 정확히 입력해주세요.")

# 2. 데이터 표시 및 요약
portfolio = get_portfolio_from_db()

if portfolio:
    data_list = []
    t_cost, t_eval = 0.0, 0.0
    
    with st.spinner('실시간 시세 반영 중...'):
        for item in portfolio:
            curr, _, _ = get_finance_data(item['ticker'])
            cost = item['buy_price'] * item['quantity']
            eval_v = curr * item['quantity']
            t_cost += cost
            t_eval += eval_v
            
            data_list.append({
                "ID": item['id'],
                "종목": item['name'],
                "티커": item['ticker'],
                "수량": item['quantity'],
                "평단가": item['buy_price'],
                "현재가": curr,
                "매수금액": cost,
                "평가금액": eval_v,
                "수익금": eval_v - cost,
                "수익률": ((eval_v / cost - 1) * 100) if cost > 0 else 0.0
            })

    # 요약 메트릭
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("총 매수금액", f"{t_cost:,.0f}")
    s2.metric("총 평가금액", f"{t_eval:,.0f}")
    diff = t_eval - t_cost
    s3.metric("총 손익", f"{diff:,.0f}", f"{(diff/t_cost*100 if t_cost > 0 else 0):+.2f}%")
    s4.metric("종목 수", f"{len(portfolio)}개")

    # 데이터 테이블
    df_p = pd.DataFrame(data_list)
    # 가독성을 위한 포맷팅
    display_df = df_p.copy()
    format_cols = ["평단가", "현재가", "매수금액", "평가금액", "수익금"]
    for col in format_cols:
        display_df[col] = display_df[col].apply(lambda x: f"{x:,.0f}")
    display_df["수익률"] = display_df["수익률"].apply(lambda x: f"{x:+.2f}%")
    
    st.dataframe(display_df.drop(columns="ID"), use_container_width=True)

    # 삭제 기능
    c_del1, c_del2 = st.columns([3, 1])
    del_target_name = c_del1.selectbox("삭제할 종목 선택", df_p['종목'].tolist())
    if c_del2.button("선택 종목 삭제", use_container_width=True):
        target_id = df_p[df_p['종목'] == del_target_name]['ID'].values[0]
        delete_from_portfolio(target_id)
        st.rerun()
else:
    st.info("등록된 종목이 없습니다. 상단의 등록 폼을 이용해 종목을 추가하세요.")

# 사이드바 설정
with st.sidebar:
    st.header("설정")
    if st.button("🔄 강제 새로고침", use_container_width=True):
        st.rerun()
    st.write("---")
    st.write("본 대시보드는 실시간 데이터(yfinance)를 기반으로 작동하며, 실제 투자 결과와 차이가 있을 수 있습니다.")
