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

# --- 3. 데이터 수집 보조 함수 ---
def get_naver_ticker_info(code):
    """네이버 금융 파싱: 실시간 시세 및 펀더멘털"""
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        no_today = soup.select_one(".no_today")
        blind = no_today.select_one(".blind") if no_today else None
        price = float(blind.text.replace(",", "")) if blind else 0.0
        
        no_exday = soup.select_one(".no_exday")
        diff_text = no_exday.select_one(".blind").text.replace(",", "") if no_exday else "0"
        is_down = "ico_down" in str(no_exday)
        diff = -float(diff_text) if is_down else float(diff_text)
        
        rate_tag = soup.select_one(".no_today").find_next_sibling("td")
        rate_text = rate_tag.select_one(".blind").text.replace("%", "") if rate_tag else "0"
        pct = float(rate_text) * (-1 if is_down else 1)

        fundamental = {}
        tab_con = soup.select_one(".tab_con1")
        if tab_con:
            for tr in tab_con.select("tr"):
                th, td = tr.select_one("th"), tr.select_one("td")
                if th and td:
                    label = th.text.strip()
                    val = td.text.strip().replace(",", "").replace("배", "").replace("%", "")
                    fundamental[label] = val

        return {"price": price, "change": diff, "pct": pct, "fundamental": fundamental}
    except: return None

@st.cache_data(ttl=60)
def get_finance_data(ticker):
    match = re.match(r'^(\d{6})', ticker)
    if match:
        data = get_naver_ticker_info(match.group(1))
        if data and data['price'] > 0: return data['price'], data['change'], data['pct']
    
    try:
        yt = yf.Ticker(ticker)
        hist = yt.history(period="5d")
        if not hist.empty and len(hist) >= 2:
            p = hist['Close'].iloc[-1]
            c = p - hist['Close'].iloc[-2]
            return float(p), float(c), float((c/hist['Close'].iloc[-2])*100)
    except: pass
    return 0.0, 0.0, 0.0

@st.cache_data(ttl=300)
def get_chart_data(ticker, period="1개월"):
    """기간별 차트 데이터 수집 (년/월/일 대응)"""
    try:
        yf_ticker = ticker + ".KS" if re.match(r'^\d{6}$', ticker) else ticker
        yt = yf.Ticker(yf_ticker)
        
        # 기간 매핑
        period_map = {"1일": "1d", "1개월": "1mo", "3개월": "3mo", "1년": "1y", "5년": "5y"}
        p = period_map.get(period, "1mo")
        interval = "5m" if p == "1d" else "1d"
        
        data = yt.history(period=p, interval=interval)
        return data[['Close']]
    except: return pd.DataFrame()

def validate_and_get_ticker(name):
    """입력된 종목명/코드를 검증하고 유효한 티커를 반환합니다."""
    query = name.strip()
    if not query: return None

    # 1. 한국 종목 검색 (네이버 API)
    try:
        res = requests.get(f"https://ac.finance.naver.com/ac?q={query}&st=111&r_format=json&t_koreng=1", timeout=5).json()
        items = res.get('items', [[]])[0]
        if items: 
            # 검색 결과 중 가장 관련성 높은 코드 반환 (숫자 6자리)
            return items[0][1]
    except: pass
    
    # 2. 해외 종목 검색 (야후 API)
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(f"https://query2.finance.yahoo.com/v1/finance/search?q={query}", headers=headers, timeout=5).json()
        if res.get('quotes'): 
            return res['quotes'][0]['symbol']
    except: pass
    
    # 3. 직접 티커 입력 시 (숫자 6자리 또는 영문 대문자 검증)
    if re.match(r'^\d{6}$', query): return query
    if query.isalpha(): return query.upper()
    
    return None

# --- 4. Firestore CRUD ---
def db_action(action, doc_id=None, data=None):
    if db is None: return False
    try:
        col = db.collection(COLLECTION_NAME)
        if action == "add": col.add(data)
        elif action == "update": col.document(doc_id).update(data)
        elif action == "delete": col.document(doc_id).delete()
        return True
    except: return False

# --- 5. UI 구성 ---
st.title("📊 Global Finance Dashboard V2.1")

if db is not None:
    # --- 1. 상단 지표 ---
    st.subheader("🌐 글로벌 시장 주요 지표")
    idx_period = st.radio("지표 기간 선택", ["1일", "1개월", "1년"], index=1, horizontal=True, label_visibility="collapsed")
    indices = [("^KS11", "KOSPI"), ("^KQ11", "KOSDAQ"), ("^IXIC", "NASDAQ"), ("^GSPC", "S&P500"), ("KRW=X", "USD/KRW"), ("BTC-USD", "BTC")]
    idx_cols = st.columns(len(indices))
    
    for i, (ticker, label) in enumerate(indices):
        price, _, pct = get_finance_data(ticker)
        color = "#FF4B4B" if pct > 0 else "#1C83E1" if pct < 0 else "#A0A0A0"
        with idx_cols[i]:
            st.metric(label, f"{price:,.2f}", f"{pct:+.2f}%")
            spark_df = get_chart_data(ticker, idx_period)
            if not spark_df.empty:
                fig = go.Figure(go.Scatter(y=spark_df['Close'], mode='lines', line=dict(color=color, width=2)))
                fig.update_layout(height=40, margin=dict(l=0, r=0, t=0, b=0), xaxis_visible=False, yaxis_visible=False, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False}, key=f"spark_{ticker}")

    st.divider()

    # --- 2. 메인 본문 ---
    col_left, col_right = st.columns([3.2, 1.8])

    with col_left:
        st.subheader("💼 내 포트폴리오 관리")
        
        portfolio_raw = [{"id": d.id, **d.to_dict()} for d in db.collection(COLLECTION_NAME).stream()]
        
        with st.expander("➕ 종목 등록 / 📝 수정 / 🗑️ 삭제", expanded=False):
            edit_target = st.selectbox("수정할 종목 선택 (새 등록은 '신규 등록')", ["신규 등록"] + [p['name'] for p in portfolio_raw])
            target_data = next((p for p in portfolio_raw if p['name'] == edit_target), None)
            
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("종목명 (예: 삼성전자, AAPL)", value=target_data['name'] if target_data else "")
            buy_p = c2.number_input("평단가", value=float(target_data['buy_price']) if target_data else 0.0, min_value=0.0)
            qty = c3.number_input("수량", value=int(target_data['quantity']) if target_data else 0, min_value=0)
            
            c4, c5, c6 = st.columns(3)
            sl_val = c4.number_input("손절가 (%)", value=float(target_data.get('sl', -10.0)) if target_data else -10.0)
            tp_val = c5.number_input("익절가 (%)", value=float(target_data.get('tp', 20.0)) if target_data else 20.0)
            b_date = c6.date_input("매수일", value=target_data['buy_date'].date() if target_data else datetime.now())
            
            btn_col1, btn_col2 = st.columns(2)
            if btn_col1.button("저장하기", use_container_width=True, type="primary"):
                # --- 유효성 검증 로직 시작 ---
                if not name:
                    st.error("종목명을 입력해주세요.")
                elif buy_p <= 0:
                    st.error("평단가는 0보다 커야 합니다.")
                elif qty <= 0:
                    st.error("수량은 1개 이상이어야 합니다.")
                else:
                    with st.spinner('종목 정보를 확인 중입니다...'):
                        validated_ticker = validate_and_get_ticker(name)
                        if validated_ticker:
                            payload = {
                                "name": name, "ticker": validated_ticker, "buy_price": buy_p, 
                                "quantity": qty, "sl": sl_val, "tp": tp_val, 
                                "buy_date": datetime.combine(b_date, datetime.min.time()), 
                                "created_at": datetime.now()
                            }
                            if target_data: 
                                if db_action("update", target_data['id'], payload):
                                    st.success(f"{name} 정보가 수정되었습니다.")
                                    st.rerun()
                            else: 
                                if db_action("add", data=payload):
                                    st.success(f"{name} 종목이 등록되었습니다.")
                                    st.rerun()
                        else:
                            st.error(f"'{name}'에 해당하는 시장 티커를 찾을 수 없습니다. 정확한 종목명이나 티커를 입력해주세요.")
                # --- 유효성 검증 로직 끝 ---
            
            if target_data and btn_col2.button("삭제하기", use_container_width=True):
                if db_action("delete", target_data['id']):
                    st.warning(f"{target_data['name']} 종목이 삭제되었습니다.")
                    st.rerun()

        # 포트폴리오 목록
        if portfolio_raw:
            display_rows = []
            for item in portfolio_raw:
                curr, _, _ = get_finance_data(item['ticker'])
                profit_v = (curr - item['buy_price']) * item['quantity']
                profit_p = (curr / item['buy_price'] - 1) * 100 if item['buy_price'] > 0 else 0
                
                display_rows.append({
                    "종목": item['name'],
                    "평단가": item['buy_price'],
                    "수익률": profit_p,
                    "수익금": profit_v,
                    "현재가": curr,
                    "손절가(%)": item.get('sl', -10.0),
                    "익절가(%)": item.get('tp', 20.0),
                    "티커": item['ticker']
                })
            
            df = pd.DataFrame(display_rows)
            
            def style_portfolio(row):
                styles = [''] * len(row)
                p_color = 'color: #FF4B4B' if row['수익률'] > 0 else 'color: #1C83E1' if row['수익률'] < 0 else ''
                styles[2] = p_color + '; font-weight: bold'
                styles[3] = p_color + '; font-weight: bold'
                styles[5] = 'color: #1C83E1; font-weight: 900'
                styles[6] = 'color: #28A745; font-weight: 900'
                return styles

            st.dataframe(
                df.style.apply(style_portfolio, axis=1).format({
                    "평단가": "{:,.0f}", "현재가": "{:,.0f}", "수익률": "{:+.2f}%", "수익금": "{:,.0f}"
                }),
                use_container_width=True, hide_index=True
            )
        else:
            st.info("등록된 종목이 없습니다. 상단에서 종목을 추가해 주세요.")

    with col_right:
        st.subheader("🔍 종목 정밀 분석")
        if portfolio_raw:
            ana_name = st.selectbox("분석 대상", [p['name'] for p in portfolio_raw])
            ana_item = next(p for p in portfolio_raw if p['name'] == ana_name)
            
            ana_period = st.radio("분석 기간", ["1일", "1개월", "3개월", "1년", "5년"], index=1, horizontal=True)
            
            st.write(f"📈 **{ana_name}** 주가 흐름 ({ana_period})")
            c_data = get_chart_data(ana_item['ticker'], ana_period)
            if not c_data.empty:
                fig = go.Figure(go.Scatter(
                    x=c_data.index, y=c_data['Close'], 
                    line=dict(color='#00CC96', width=2), 
                    fill='tozeroy', fillcolor='rgba(0, 204, 150, 0.1)'
                ))
                fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), template="plotly_white", xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)
            
            match = re.match(r'^(\d{6})', ana_item['ticker'])
            if match:
                st.markdown("🏛️ **상세 가치 지표**")
                n_info = get_naver_ticker_info(match.group(1))
                if n_info and n_info['fundamental']:
                    f = n_info['fundamental']
                    m1, m2, m3 = st.columns(3)
                    m1.metric("PER", f"{f.get('PER', 'N/A')}배")
                    m2.metric("PBR", f"{f.get('PBR', 'N/A')}배")
                    m3.metric("ROE", f"{f.get('ROE', 'N/A')}%")
                    with st.expander("전체 지표 리스트"):
                        st.table(pd.DataFrame({"지표": f.keys(), "값": f.values()}))
            else:
                st.info("해외 종목은 상세 재무 지표 조회가 제한됩니다.")

st.sidebar.button("♻️ 데이터 강제 갱신", on_click=lambda: st.cache_data.clear())
