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
    page_title="Global Financial Dashboard V2.2",
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
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
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
    """기간별 차트 데이터 수집"""
    try:
        if re.match(r'^\d{6}$', ticker):
            for suffix in [".KS", ".KQ"]:
                yt = yf.Ticker(ticker + suffix)
                period_map = {"1일": "1d", "1개월": "1mo", "3개월": "3mo", "1년": "1y", "5년": "5y"}
                p = period_map.get(period, "1mo")
                interval = "5m" if p == "1d" else "1d"
                data = yt.history(period=p, interval=interval)
                if not data.empty: return data[['Close']]
            return pd.DataFrame()
        else:
            yt = yf.Ticker(ticker)
            period_map = {"1일": "1d", "1개월": "1mo", "3개월": "3mo", "1년": "1y", "5년": "5y"}
            p = period_map.get(period, "1mo")
            interval = "5m" if p == "1d" else "1d"
            data = yt.history(period=p, interval=interval)
            return data[['Close']]
    except: return pd.DataFrame()

def validate_and_get_ticker(name):
    """종목명/코드를 검증하고 유효한 티커 반환"""
    query = name.strip()
    if not query: return None
    try:
        search_url = f"https://ac.finance.naver.com/ac?q={query}&st=111&r_format=json&t_koreng=1"
        res = requests.get(search_url, timeout=5).json()
        if res.get('items') and len(res['items'][0]) > 0:
            return res['items'][0][0][1]
    except: pass
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(f"https://query2.finance.yahoo.com/v1/finance/search?q={query}", headers=headers, timeout=5).json()
        if res.get('quotes'): return res['quotes'][0]['symbol']
    except: pass
    if re.match(r'^\d{6}$', query): return query
    if re.match(r'^[A-Z.=-]{1,10}$', query.upper()): return query.upper()
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
st.title("📊 Global Finance Dashboard V2.2")

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
            name = c1.text_input("종목명", value=target_data['name'] if target_data else "")
            buy_p = c2.number_input("평단가", value=float(target_data['buy_price']) if target_data else 0.0, min_value=0.0)
            qty = c3.number_input("수량", value=int(target_data['quantity']) if target_data else 0, min_value=0)
            
            c4, c5, c6 = st.columns(3)
            sl_val = c4.number_input("손절가 (%)", value=float(target_data.get('sl', -10.0)) if target_data else -10.0)
            tp_val = c5.number_input("익절가 (%)", value=float(target_data.get('tp', 20.0)) if target_data else 20.0)
            b_date = c6.date_input("매수일", value=target_data['buy_date'].date() if target_data else datetime.now())

            c7, c8 = st.columns([1, 2])
            # 신규 추가: 매도일 및 매매일지
            s_date = c7.date_input("매도(예정)일", value=target_data.get('sell_date', datetime.now() + timedelta(days=30)).date() if target_data and 'sell_date' in target_data else datetime.now() + timedelta(days=30))
            note = c8.text_area("📝 매매일지 / 메모", value=target_data.get('note', "") if target_data else "", placeholder="매수 근거, 전략 등을 기록하세요.", height=100)
            
            btn_col1, btn_col2 = st.columns(2)
            if btn_col1.button("저장하기", use_container_width=True, type="primary"):
                if not name.strip(): st.error("종목명을 입력해주세요.")
                elif buy_p <= 0: st.error("평단가는 0보다 커야 합니다.")
                elif qty <= 0: st.error("수량은 1개 이상이어야 합니다.")
                else:
                    with st.spinner('유효성 검증 중...'):
                        validated_ticker = validate_and_get_ticker(name)
                        if validated_ticker:
                            payload = {
                                "name": name, "ticker": validated_ticker, "buy_price": buy_p, 
                                "quantity": qty, "sl": sl_val, "tp": tp_val, 
                                "buy_date": datetime.combine(b_date, datetime.min.time()),
                                "sell_date": datetime.combine(s_date, datetime.min.time()),
                                "note": note,
                                "created_at": datetime.now()
                            }
                            if target_data: 
                                if db_action("update", target_data['id'], payload): st.rerun()
                            else: 
                                if db_action("add", data=payload): st.rerun()
                        else: st.error(f"'{name}'의 티커를 찾을 수 없습니다.")
            
            if target_data and btn_col2.button("삭제하기", use_container_width=True):
                if db_action("delete", target_data['id']): st.rerun()

        # 포트폴리오 목록
        if portfolio_raw:
            display_rows = []
            for item in portfolio_raw:
                curr, _, _ = get_finance_data(item['ticker'])
                profit_p = (curr / item['buy_price'] - 1) * 100 if item['buy_price'] > 0 else 0
                
                display_rows.append({
                    "종목": item['name'],
                    "평단가": item['buy_price'],
                    "현재가": curr,
                    "수익률": profit_p,
                    "매수일": item['buy_date'].strftime('%Y-%m-%d'),
                    "매도일": item.get('sell_date', datetime.now()).strftime('%Y-%m-%d') if 'sell_date' in item else "-",
                    "메모": "📝" if item.get('note') else ""
                })
            
            df = pd.DataFrame(display_rows)
            st.dataframe(
                df.style.apply(lambda x: ['color: #FF4B4B' if x['수익률'] > 0 else 'color: #1C83E1' if x['수익률'] < 0 else ''] * len(x), axis=1)
                .format({"평단가": "{:,.0f}", "현재가": "{:,.0f}", "수익률": "{:+.2f}%"}),
                use_container_width=True, hide_index=True
            )
        else:
            st.info("등록된 종목이 없습니다.")

    with col_right:
        st.subheader("🔍 종목 정밀 분석")
        if portfolio_raw:
            ana_name = st.selectbox("분석 대상 선택", [p['name'] for p in portfolio_raw])
            ana_item = next(p for p in portfolio_raw if p['name'] == ana_name)
            
            # 매매일지 표시 섹션
            if ana_item.get('note'):
                with st.chat_message("user", avatar="📝"):
                    st.markdown(f"**매매일지:** \n{ana_item['note']}")
            
            ana_period = st.radio("분석 기간", ["1일", "1개월", "3개월", "1년", "5년"], index=1, horizontal=True)
            c_data = get_chart_data(ana_item['ticker'], ana_period)
            if not c_data.empty:
                fig = go.Figure(go.Scatter(x=c_data.index, y=c_data['Close'], line=dict(color='#00CC96', width=2), fill='tozeroy', fillcolor='rgba(0, 204, 150, 0.1)'))
                fig.update_layout(height=250, margin=dict(l=0, r=0, t=10, b=0), template="plotly_white", xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)
            
            match = re.match(r'^(\d{6})', ana_item['ticker'])
            if match:
                n_info = get_naver_ticker_info(match.group(1))
                if n_info and n_info['fundamental']:
                    f = n_info['fundamental']
                    m1, m2, m3 = st.columns(3)
                    m1.metric("PER", f"{f.get('PER', 'N/A')}배")
                    m2.metric("PBR", f"{f.get('PBR', 'N/A')}배")
                    m3.metric("ROE", f"{f.get('ROE', 'N/A')}%")
            else:
                st.info("해외 종목 상세 지표 제한")

st.sidebar.button("♻️ 데이터 강제 갱신", on_click=lambda: st.cache_data.clear())
