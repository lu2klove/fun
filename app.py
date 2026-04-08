import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
from google.cloud import firestore
from google.oauth2 import service_account
import json

--- 1. 페이지 설정 ---
st.set_page_config(
page_title="Global Financial Dashboard",
page_icon="📈",
layout="wide"
)

--- 2. Firestore 데이터베이스 초기화 ---
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

--- 3. DB 핸들링 함수 ---
def get_portfolio_from_db():
if db is None: return []
try:
docs = db.collection(COLLECTION_NAME).order_by("created_at").stream()
return [{"id": d.id, **d.to_dict()} for d in docs]
except: return []

def add_to_portfolio(name, ticker, buy_price, quantity):
if db:
db.collection(COLLECTION_NAME).add({
"name": name, "ticker": ticker, "buy_price": buy_price,
"quantity": quantity, "created_at": datetime.now()
})

def delete_from_portfolio(doc_id):
if db:
db.collection(COLLECTION_NAME).document(doc_id).delete()

--- 4. 데이터 수집 함수 ---
@st.cache_data(ttl=60)
def get_finance_data(ticker):
try:
yt = yf.Ticker(ticker)
data = yt.history(period="1d")
if not data.empty:
price = data['Close'].iloc[-1]
prev_price = data['Open'].iloc[-1]
change = price - prev_price
return price, change, (change / prev_price) * 100
except: return 0.0, 0.0, 0.0

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
except: pass
return pd.DataFrame()

COMPANY_TICKER_MAP = {
"삼성전자": "005930.KS", "SK하이닉스": "000660.KS", "애플": "AAPL", "테슬라": "TSLA"
}

def get_ticker_from_name(name):
clean = name.strip().replace(" ", "")
return COMPANY_TICKER_MAP.get(clean, clean.upper())

--- 5. UI 구성 ---
st.title("📊 실시간 글로벌 경제 지표 대시보드")
st.caption(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

지수 비교
col_left, col_right = st.columns(2)
period_map = {"1일": "1d", "1개월": "1mo", "1년": "1y"}

with col_left:
st.subheader("🇰🇷 국내 증시")
k_p_label = st.radio("기간 (국내)", ["1일", "1개월", "1년"], index=1, horizontal=True)
p1, _, pct1 = get_finance_data("^KS11")
p2, _, pct2 = get_finance_data("^KQ11")
st.columns(2)[0].metric("KOSPI", f"{p1:,.2f}", f"{pct1:+.2f}%")
st.columns(2)[1].metric("KOSDAQ", f"{p2:,.2f}", f"{pct2:+.2f}%")
df = get_chart_data("^KS11", "KOSPI", period_map[k_p_label])
if not df.empty: st.line_chart(df)

with col_right:
st.subheader("🇺🇸 미국 증시")
u_p_label = st.radio("기간 (미국)", ["1일", "1개월", "1년"], index=1, horizontal=True)
p1, _, pct1 = get_finance_data("^GSPC")
p2, _, pct2 = get_finance_data("^IXIC")
st.columns(2)[0].metric("S&P 500", f"{p1:,.2f}", f"{pct1:+.2f}%")
st.columns(2)[1].metric("NASDAQ", f"{p2:,.2f}", f"{pct2:+.2f}%")
df = get_chart_data("^IXIC", "NASDAQ", period_map[u_p_label])
if not df.empty: st.line_chart(df)

st.divider()

보유 종목 관리 섹션 (추가됨)
st.subheader("💼 내 보유 종목 포트폴리오 관리")

입력창
with st.container():
c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
in_name = c1.text_input("종목명/티커")
in_buy = c2.number_input("평단가", min_value=0.0)
in_qty = c3.number_input("수량", min_value=0)
if c4.button("등록") and in_name and in_buy > 0:
add_to_portfolio(in_name, get_ticker_from_name(in_name), in_buy, in_qty)
st.rerun()

데이터 테이블
portfolio = get_portfolio_from_db()
if portfolio:
data_list = []
t_cost, t_eval = 0, 0
for item in portfolio:
curr, _, _ = get_finance_data(item['ticker'])
cost = item['buy_price'] * item['quantity']
eval_v = curr * item['quantity']
t_cost += cost
t_eval += eval_v
data_list.append({
"종목": item['name'], "수량": item['quantity'],
"평단": f"{item['buy_price']:,.0f}", "현재가": f"{curr:,.0f}",
"수익금": f"{eval_v - cost:,.0f}",
"수익률": f"{(eval_v/cost-1)*100:+.2f}%" if cost > 0 else "0%",
"ID": item['id']
})

# 요약
s1, s2, s3 = st.columns(3)
s1.metric("총 매수금액", f"{t_cost:,.0f}원")
s2.metric("총 평가금액", f"{t_eval:,.0f}원")
s3.metric("총 손익", f"{t_eval-t_cost:,.0f}원", f"{(t_eval/t_cost-1)*100:+.2f}%" if t_cost > 0 else "0%")

df_p = pd.DataFrame(data_list)
st.dataframe(df_p.drop(columns="ID"), use_container_width=True)

del_target = st.selectbox("삭제할 종목 선택", df_p['종목'].tolist())
if st.button("선택 삭제"):
    tid = df_p[df_p['종목'] == del_target]['ID'].values[0]
    delete_from_portfolio(tid)
    st.rerun()
else:
st.info("등록된 종목이 없습니다.")

st.sidebar.button("새로고침", on_click=lambda: st.rerun())
