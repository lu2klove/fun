import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
from google.cloud import firestore
from google.oauth2 import service_account
import json
import requests
import re
from bs4 import BeautifulSoup

# --- 1. 페이지 설정 ---
st.set_page_config(
    page_title="Global Financial Dashboard V2.6",
    page_icon="📈",
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

# --- 3. 데이터 수집 보조 함수 (네이버 금융) ---
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
        # 상승/하락 구분
        is_down = "ico_down" in str(no_exday)
        diff = -float(diff_text) if is_down else float(diff_text)
        
        rate_text = soup.select_one(".no_today").find_next_sibling("td").select_one(".blind").text.replace("%", "") if soup.select_one(".no_today") else "0"
        pct = float(rate_text) * (-1 if is_down else 1)

        # 펀더멘털 지표 (PER, PBR 등)
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

        return {
            "price": price,
            "change": diff,
            "pct": pct,
            "fundamental": fundamental
        }
    except:
        return None

# --- 4. 데이터 수집 및 검색 함수 ---
@st.cache_data(ttl=60)
def get_finance_data(ticker):
    # 한국 종목 코드(6자리 숫자)인 경우 네이버 우선
    match = re.match(r'^(\d{6})', ticker)
    if match:
        code = match.group(1)
        naver_data = get_naver_ticker_info(code)
        if naver_data and naver_data['price'] > 0:
            return naver_data['price'], naver_data['change'], naver_data['pct']
    
    # 그 외 또는 실패 시 yfinance
    try:
        yt = yf.Ticker(ticker)
        # .info를 쓰지 않고 history에서 최신 가격만 가져옴 (Rate Limit 방지)
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
                code = items[0][1]
                return code # 6자리 코드 반환
    except:
        pass
    return None

def validate_and_get_ticker(name):
    """종목 등록 시 네이버를 최우선으로 검색합니다."""
    clean = name.strip()
    if not clean: return None
    
    # 1. 한국 종목 검색 (네이버 우선)
    kr_ticker = search_ticker_korea(clean)
    if kr_ticker: return kr_ticker
        
    # 2. 글로벌 검색 (Yahoo Finance)
    ticker_candidate = None
    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={clean}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get('quotes'):
                ticker_candidate = data['quotes'][0]['symbol']
    except:
        pass
    
    if not ticker_candidate and clean.replace(".","").replace("-","").isalnum():
        ticker_candidate = clean.upper()
    
    return ticker_candidate

# --- 5. DB 및 차트 함수 ---
def get_portfolio_from_db():
    if db is None: return []
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        results = [{"id": d.id, **d.to_dict()} for d in docs]
        results.sort(key=lambda x: x.get('created_at', datetime.min), reverse=True)
        return results
    except: return []

def add_to_portfolio(name, ticker, buy_price, quantity, stop_loss_pct, tp1_pct, tp_f_pct, buy_date, trading_log):
    if db is None: return False
    try:
        db.collection(COLLECTION_NAME).add({
            "name": name, "ticker": ticker, "buy_price": float(buy_price), "quantity": int(quantity),
            "stop_loss_pct": float(stop_loss_pct), "tp1_pct": float(tp1_pct), "tp_final_pct": float(tp_f_pct),
            "buy_date": datetime.combine(buy_date, datetime.min.time()), "trading_log": trading_log, "created_at": datetime.now()
        })
        return True
    except: return False

@st.cache_data(ttl=300)
def get_chart_data(ticker, name, period="1mo"):
    try:
        # yfinance용 티커 보정 (숫자 6자리면 .KS 붙임)
        yf_ticker = ticker + ".KS" if re.match(r'^\d{6}$', ticker) else ticker
        yt = yf.Ticker(yf_ticker)
        interval = "5m" if period == "1d" else "1d"
        data = yt.history(period=period, interval=interval)
        if not data.empty:
            df = data[['Close']].copy()
            df.columns = [name]
            return df
    except: return pd.DataFrame()

# --- 6. UI 구성 ---
st.title("📊 글로벌 경제 통합 대시보드")
st.caption(f"네이버 금융 중심 엔진 V2.6 (Rate Limit 최적화) | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if db is not None:
    # --- 주요 지표 ---
    st.subheader("🌐 주요 시장 지표")
    indices_list = [("^KS11", "KOSPI"), ("^KQ11", "KOSDAQ"), ("^IXIC", "NASDAQ"), ("^GSPC", "S&P500"), ("KRW=X", "USD/KRW"), ("BTC-USD", "Bitcoin")]
    idx_cols = st.columns(len(indices_list))
    for i, (ticker, name) in enumerate(indices_list):
        p, _, pct = get_finance_data(ticker)
        idx_cols[i].metric(name, f"{p:,.2f}", f"{pct:+.2f}%")

    st.divider()
    col_list, col_chart = st.columns([3, 2])

    with col_list:
        st.subheader("💼 내 포트폴리오 관리")
        with st.expander("➕ 새 종목 등록", expanded=False):
            c1, c2, c3 = st.columns(3)
            in_name = c1.text_input("종목명 (네이버 검색 우선)", key="reg_name")
            in_buy = c2.number_input("평단가", min_value=0.0)
            in_qty = c3.number_input("수량", min_value=0)
            if st.button("포트폴리오 추가", use_container_width=True):
                valid_ticker = validate_and_get_ticker(in_name)
                if valid_ticker and add_to_portfolio(in_name, valid_ticker, in_buy, in_qty, -10, 20, 50, datetime.now(), ""):
                    st.success(f"{in_name} 등록 완료!")
                    st.rerun()
                else: st.error("종목을 찾을 수 없습니다.")

        portfolio = get_portfolio_from_db()
        if portfolio:
            display_data = []
            for item in portfolio:
                curr, _, pct = get_finance_data(item['ticker'])
                cost = item['buy_price'] * item['quantity']
                eval_v = curr * item['quantity']
                display_data.append({
                    "종목": item['name'], "티커": item['ticker'], "현재가": curr, "수익률": (eval_v/cost-1)*100 if cost>0 else 0,
                    "수익금": eval_v - cost, "ID": item['id'], "Raw": item
                })
            st.dataframe(pd.DataFrame(display_data).drop(columns=["ID", "Raw"]), use_container_width=True, hide_index=True)

    with col_chart:
        st.subheader("🔍 종목 심층 분석")
        analysis_name = st.selectbox("분석 종목 선택", [d['종목'] for d in display_data] if portfolio else ["삼성전자"])
        
        # 분석할 종목의 티커 확인
        analysis_ticker = next((d['티커'] for d in display_data if d['종목'] == analysis_name), validate_and_get_ticker(analysis_name))
        
        # 차트 출력
        chart_df = get_chart_data(analysis_ticker, analysis_name, "1mo")
        if not chart_df.empty: st.line_chart(chart_df)
        
        st.markdown("---")
        st.write("🏛️ **상세 펀더멘털 및 가치 지표 (네이버 기준)**")
        
        # 네이버 금융에서 펀더멘털 데이터 가져오기 (차단 위험이 적음)
        match = re.match(r'^(\d{6})', analysis_ticker)
        naver_info = None
        if match:
            naver_info = get_naver_ticker_info(match.group(1))
            
        if naver_info and naver_info['fundamental']:
            f = naver_info['fundamental']
            m1, m2, m3 = st.columns(3)
            m1.metric("현재가", f"{naver_info['price']:,.0f}")
            m2.metric("PER", f"{f.get('PER', 'N/A')}배")
            m3.metric("PBR", f"{f.get('PBR', 'N/A')}배")
            
            with st.expander("전체 지표 리스트", expanded=True):
                st.table(pd.DataFrame({"지표": f.keys(), "값": f.values()}))
        else:
            # yfinance 폴백 (Rate Limit 대응: .info 대신 history 마지막 값 활용)
            try:
                curr, _, _ = get_finance_data(analysis_ticker)
                if curr > 0:
                    st.metric("현재가", f"{curr:,.2f}")
                    st.info("야후 파이낸스 요청 제한으로 인해 상세 펀더멘털 정보를 표시할 수 없습니다. 나중에 다시 시도해주세요.")
                else:
                    st.warning("데이터를 불러올 수 없습니다.")
            except:
                st.warning("현재 서비스 호출량이 많아 데이터를 불러올 수 없습니다.")

st.sidebar.button("♻️ 새로고침", on_click=lambda: st.cache_data.clear())
