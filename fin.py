import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from google.cloud import firestore
from google.oauth2 import service_account
import json
import requests
import re
from bs4 import BeautifulSoup

# --- 1. 페이지 설정 ---
st.set_page_config(
    page_title="Global Financial Dashboard V2.1",
    page_icon="🚀",
    layout="wide"
)

# --- 2. Firestore 초기화 ---
@st.cache_resource
def init_db():
    try:
        if "firebase" in st.secrets:
            raw_json = st.secrets["firebase"]["text_key"]
            try:
                key_dict = json.loads(raw_json, strict=False)
            except json.JSONDecodeError:
                fixed_json = re.sub(r'[\x00-\x1F\x7F]', '', raw_json)
                key_dict = json.loads(fixed_json)
            
            if "private_key" in key_dict:
                key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n").strip()
                
            creds = service_account.Credentials.from_service_account_info(key_dict)
            client = firestore.Client(
                credentials=creds, 
                project=key_dict.get('project_id'),
                database="richfin"
            )
            return client
        return None
    except Exception as e:
        st.error(f"DB 연결 오류: {e}")
        return None

db = init_db()
COLLECTION_NAME = "my_portfolio"

# --- 3. 데이터 수집 보조 함수 (네이버 금융 파싱) ---
def get_naver_ticker_info(code):
    """네이버 금융에서 종목의 실시간 시세 및 기본 정보를 가져옵니다."""
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 현재가 추출
        no_today = soup.select_one(".no_today")
        blind = no_today.select_one(".blind") if no_today else None
        price = float(blind.text.replace(",", "")) if blind else 0.0
        
        # 전일비 및 등락률
        no_exday = soup.select_one(".no_exday")
        diff_text = no_exday.select_one(".blind").text.replace(",", "") if no_exday else "0"
        is_down = "ico_down" in str(no_exday)
        diff = -float(diff_text) if is_down else float(diff_text)
        
        rate_tag = soup.select_one(".no_today").find_next_sibling("td")
        rate_text = rate_tag.select_one(".blind").text.replace("%", "") if rate_tag else "0"
        pct = float(rate_text) * (-1 if is_down else 1)

        # 펀더멘털 지표
        fundamental = {}
        tab_con = soup.select_one(".tab_con1")
        if tab_con:
            trs = tab_con.select("tr")
            for tr in trs:
                th = tr.select_one("th")
                td = tr.select_one("td")
                if th and td:
                    label = th.text.strip()
                    val = td.text.strip().replace(",", "").replace("배", "").replace("%", "")
                    fundamental[label] = val

        return {"price": price, "change": diff, "pct": pct, "fundamental": fundamental}
    except:
        return None

@st.cache_data(ttl=60)
def get_finance_data(ticker):
    """네이버 우선, yfinance 차선책으로 시세 데이터를 가져옵니다."""
    # 한국 종목 코드(6자리 숫자)인 경우 네이버 우선
    match = re.match(r'^(\d{6})', ticker)
    if match:
        code = match.group(1)
        naver_data = get_naver_ticker_info(code)
        if naver_data and naver_data['price'] > 0:
            return naver_data['price'], naver_data['change'], naver_data['pct']
    
    # 그 외 또는 실패 시 yfinance (Rate Limit 방지를 위해 history 사용)
    try:
        yt = yf.Ticker(ticker)
        data = yt.history(period="5d")
        if not data.empty and len(data) >= 2:
            price = data['Close'].iloc[-1]
            prev_price = data['Close'].iloc[-2]
            change = price - prev_price
            change_pct = (change / prev_price) * 100
            return float(price), float(change), float(change_pct)
    except:
        pass
    return 0.0, 0.0, 0.0

def search_ticker_korea(query):
    """네이버 금융 검색을 활용하여 한국 종목 코드를 찾습니다."""
    try:
        url = f"https://ac.finance.naver.com/ac?q={query}&q_enc=euc-kr&st=111&frm=stock&r_format=json&r_enc=euc-kr&r_unicode=1&t_koreng=1"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            items = data.get('items', [[]])[0]
            if items:
                return items[0][1]
    except:
        pass
    return None

def validate_and_get_ticker(name):
    clean = name.strip()
    if not clean: return None
    kr_ticker = search_ticker_korea(clean)
    if kr_ticker: return kr_ticker
    
    ticker_candidate = None
    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={clean}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get('quotes'): ticker_candidate = data['quotes'][0]['symbol']
    except: pass
    
    if not ticker_candidate and clean.replace(".","").replace("-","").isalnum():
        ticker_candidate = clean.upper()
    return ticker_candidate

# --- 4. 포트폴리오 로직 ---
def get_portfolio_from_db():
    if db is None: return []
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        results = [{"id": d.id, **d.to_dict()} for d in docs]
        results.sort(key=lambda x: x.get('created_at', datetime.min), reverse=True)
        return results
    except: return []

def add_to_portfolio(name, ticker, buy_price, quantity, buy_date):
    if db is None: return False
    try:
        db.collection(COLLECTION_NAME).add({
            "name": name, "ticker": ticker, "buy_price": float(buy_price), "quantity": int(quantity),
            "buy_date": datetime.combine(buy_date, datetime.min.time()), "created_at": datetime.now()
        })
        return True
    except: return False

@st.cache_data(ttl=300)
def get_chart_data(ticker, name, period="1mo"):
    try:
        # yfinance용 티커 보정
        yf_ticker = ticker + ".KS" if re.match(r'^\d{6}$', ticker) else ticker
        yt = yf.Ticker(yf_ticker)
        data = yt.history(period=period)
        if not data.empty:
            return data[['Close']]
    except: return pd.DataFrame()

# --- 5. UI 구성 (V2.0 스타일 복구) ---
st.title("📊 Global Finance Dashboard V2.1")
st.caption(f"네이버 금융 엔진 + 시각화 복구 모드 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if db is not None:
    # --- 상단 주요 지표 (Metric + Sparkline) ---
    st.subheader("🌐 글로벌 시장 주요 지표")
    indices = [("^KS11", "KOSPI"), ("^KQ11", "KOSDAQ"), ("^IXIC", "NASDAQ"), ("^GSPC", "S&P500"), ("KRW=X", "USD/KRW"), ("BTC-USD", "Bitcoin")]
    idx_cols = st.columns(len(indices))
    
    for i, (ticker, label) in enumerate(indices):
        price, _, pct = get_finance_data(ticker)
        color = "red" if pct > 0 else "blue" if pct < 0 else "gray"
        with idx_cols[i]:
            st.metric(label, f"{price:,.2f}", f"{pct:+.2f}%")
            # 작은 차트 (Sparkline) 추가
            spark_df = get_chart_data(ticker, label, "1mo")
            if not spark_df.empty:
                fig = go.Figure()
                fig.add_trace(go.Scatter(y=spark_df['Close'], mode='lines', line=dict(color=color, width=2)))
                fig.update_layout(height=40, margin=dict(l=0, r=0, t=0, b=0), xaxis_visible=False, yaxis_visible=False, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

    st.divider()

    # --- 메인 대시보드 레이아웃 ---
    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.subheader("💼 내 포트폴리오 상황")
        
        # 종목 등록
        with st.expander("➕ 종목 추가", expanded=False):
            c1, c2, c3, c4 = st.columns(4)
            reg_name = c1.text_input("종목명/티커")
            reg_buy = c2.number_input("평단가", min_value=0.0)
            reg_qty = c3.number_input("수량", min_value=0)
            reg_date = c4.date_input("매수일", datetime.now())
            if st.button("등록하기", use_container_width=True):
                ticker = validate_and_get_ticker(reg_name)
                if ticker:
                    if add_to_portfolio(reg_name, ticker, reg_buy, reg_qty, reg_date):
                        st.success("등록되었습니다!")
                        st.rerun()
                else: st.error("종목 정보를 찾을 수 없습니다.")

        # 포트폴리오 리스트 및 색상 적용
        portfolio = get_portfolio_from_db()
        if portfolio:
            rows = []
            for item in portfolio:
                curr, _, _ = get_finance_data(item['ticker'])
                profit_pct = (curr / item['buy_price'] - 1) * 100 if item['buy_price'] > 0 else 0
                rows.append({
                    "종목": item['name'],
                    "현재가": f"{curr:,.2f}",
                    "평단가": f"{item['buy_price']:,.2f}",
                    "수익률": profit_pct,
                    "보유수량": item['quantity'],
                    "티커": item['ticker']
                })
            
            df_display = pd.DataFrame(rows)
            
            # 수익률 색상 입히기
            def color_profit(val):
                color = '#FF4B4B' if val > 0 else '#31333F' if val == 0 else '#1C83E1'
                return f'color: {color}; font-weight: bold'
            
            st.dataframe(
                df_display.style.map(color_profit, subset=['수익률']).format({"수익률": "{:+.2f}%"}),
                use_container_width=True, hide_index=True
            )

    with col_right:
        st.subheader("🔍 종목 정밀 분석")
        if portfolio:
            selected_stock_name = st.selectbox("분석 대상 선택", [p['name'] for p in portfolio])
            selected_item = next(p for p in portfolio if p['name'] == selected_stock_name)
            ticker = selected_item['ticker']
            
            # 1. 차트 섹션 (복구)
            st.write(f"📈 **{selected_stock_name} ({ticker}) 주가 추이**")
            chart_data = get_chart_data(ticker, selected_stock_name, "6mo")
            if not chart_data.empty:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['Close'], name='종가', line=dict(color='#00CC96')))
                fig.update_layout(height=250, margin=dict(l=0, r=0, t=10, b=0), template="plotly_white")
                st.plotly_chart(fig, use_container_width=True)
            
            # 2. 펀더멘털 섹션 (네이버 우선 로직)
            st.write("🏛️ **상세 가치 지표 (네이버 기준)**")
            match = re.match(r'^(\d{6})', ticker)
            naver_info = get_naver_ticker_info(match.group(1)) if match else None
            
            if naver_info and naver_info['fundamental']:
                f = naver_info['fundamental']
                m1, m2, m3 = st.columns(3)
                m1.metric("PER", f"{f.get('PER', 'N/A')}배")
                m2.metric("PBR", f"{f.get('PBR', 'N/A')}배")
                m3.metric("배당수익률", f"{f.get('배당수익률', 'N/A')}%")
                
                with st.expander("전체 지표 보기"):
                    st.table(pd.DataFrame({"지표": f.keys(), "값": f.values()}))
            else:
                # 해외 종목의 경우 yfinance 간소화 정보 (Rate Limit 우회)
                p, _, pct = get_finance_data(ticker)
                st.metric("현재가", f"{p:,.2f}", f"{pct:+.2f}%")
                st.info("해외 종목은 상세 지표 수집이 제한적일 수 있습니다.")
        else:
            st.info("포트폴리오에 종목을 추가하면 분석 차트가 표시됩니다.")

st.sidebar.button("♻️ 데이터 강제 갱신", on_click=lambda: st.cache_data.clear())
