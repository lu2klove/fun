import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
from google.cloud import firestore
from google.oauth2 import service_account
import json
import requests

# --- 1. 페이지 설정 ---
st.set_page_config(
    page_title="Global Financial Dashboard V1.7",
    page_icon="📈",
    layout="wide"
)

# --- 2. Firestore 초기화 (가장 안정적인 V1.1 방식 기반) ---
@st.cache_resource
def init_db():
    try:
        if "firebase" in st.secrets:
            raw_json = st.secrets["firebase"]["text_key"]
            key_dict = json.loads(raw_json.replace("\\n", "\n"))
            creds = service_account.Credentials.from_service_account_info(key_dict)
            # database 명시 없이 기본 연결 사용
            client = firestore.Client(credentials=creds, project=key_dict.get('project_id'))
            return client
        return None
    except Exception as e:
        st.error(f"DB 연결 오류: {e}")
        return None

db = init_db()
COLLECTION_NAME = "my_portfolio"

# --- 3. DB 핸들링 함수 (V1.2 기능 복구) ---
def get_portfolio_from_db():
    if db is None: return []
    try:
        docs = db.collection(COLLECTION_NAME).order_by("created_at", direction="DESCENDING").stream()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        st.warning(f"데이터 로드 오류: {e}")
        return []

def add_to_portfolio(name, ticker, buy_price, quantity, stop_loss_pct, tp1_pct, tp_f_pct, buy_date, trading_log):
    if db is None: return False
    try:
        db.collection(COLLECTION_NAME).add({
            "name": name, 
            "ticker": ticker, 
            "buy_price": float(buy_price), 
            "quantity": int(quantity),
            "stop_loss_pct": float(stop_loss_pct),
            "tp1_pct": float(tp1_pct),
            "tp_final_pct": float(tp_f_pct),
            "buy_date": datetime.combine(buy_date, datetime.min.time()),
            "trading_log": trading_log,
            "created_at": datetime.now()
        })
        return True
    except Exception as e:
        st.error(f"저장 오류: {e}")
        return False

def delete_from_portfolio(doc_id):
    if db:
        try:
            db.collection(COLLECTION_NAME).document(doc_id).delete()
            return True
        except Exception as e:
            st.error(f"삭제 오류: {e}")
            return False
    return False

# --- 4. 데이터 수집 함수 ---
@st.cache_data(ttl=60)
def get_finance_data(ticker):
    try:
        if not ticker: return 0.0, 0.0, 0.0
        yt = yf.Ticker(ticker)
        data = yt.history(period="5d")
        if not data.empty:
            price = data['Close'].iloc[-1]
            prev_price = data['Close'].iloc[-2] if len(data) >= 2 else price
            change = price - prev_price
            change_pct = (change / prev_price) * 100 if prev_price != 0 else 0
            return float(price), float(change), float(change_pct)
    except:
        pass
    return 0.0, 0.0, 0.0

@st.cache_data(ttl=300)
def get_chart_data(ticker, name, period="1mo"):
    try:
        yt = yf.Ticker(ticker)
        data = yt.history(period=period)
        if not data.empty:
            df = data[['Close']].copy()
            df.columns = [name]
            return df
    except:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_info_data(ticker):
    try:
        yt = yf.Ticker(ticker)
        info = yt.info
        return {
            "marketCap": info.get('marketCap') or info.get('totalAssets') or 0,
            "forwardPE": info.get('forwardPE') or info.get('trailingPE') or 0,
            "trailingPE": info.get('trailingPE') or 0,
            "priceToBook": info.get('priceToBook') or 0,
            "dividendYield": info.get('dividendYield') or 0,
            "returnOnEquity": info.get('returnOnEquity') or 0,
            "longBusinessSummary": info.get('longBusinessSummary') or info.get('shortName') or '정보 없음'
        }
    except:
        return None

# --- 5. 티커 변환 로직 (자동 검색 강화) ---
COMPANY_TICKER_MAP = {
    "삼성전자": "005930.KS", "SK하이닉스": "000660.KS", "네이버": "035420.KS",
    "카카오": "035720.KS", "현대차": "005380.KS", "애플": "AAPL", "테슬라": "TSLA",
    "엔비디아": "NVDA", "비트코인": "BTC-USD", "S&P500": "^GSPC", "나스닥": "^IXIC"
}

def search_ticker(query):
    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = res.json()
        if data.get('quotes'): return data['quotes'][0]['symbol']
    except: pass
    return None

def get_ticker_from_name(name):
    clean = name.strip()
    if clean in COMPANY_TICKER_MAP: return COMPANY_TICKER_MAP[clean]
    if clean.replace(".","").isalnum() and clean.upper() == clean: return clean
    found = search_ticker(clean)
    return found if found else clean.upper()

# --- 6. UI 구성 ---
st.title("📊 글로벌 경제 통합 대시보드 V1.7")
st.caption(f"richfin | Version: V1.7 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")

if db is None:
    st.error("❌ Firestore 연결에 실패했습니다. Secrets 설정을 확인하세요.")
else:
    # --- 최상단 주요 지표 ---
    st.subheader("🌐 주요 시장 지표")
    indices_list = [("^KS11", "KOSPI"), ("^IXIC", "NASDAQ"), ("KRW=X", "환율"), ("BTC-USD", "비트코인")]
    idx_cols = st.columns(len(indices_list))
    for i, (ticker, name) in enumerate(indices_list):
        p, _, pct = get_finance_data(ticker)
        idx_cols[i].metric(name, f"{p:,.2f}", f"{pct:+.2f}%")

    st.divider()

    col_list, col_chart = st.columns([3, 2])

    with col_list:
        st.subheader("💼 내 포트폴리오 관리")
        
        with st.expander("➕ 새 종목 등록"):
            c1, c2, c3 = st.columns(3)
            in_name = c1.text_input("종목명 (예: 삼성전자, TSLA)")
            in_buy = c2.number_input("평단가", min_value=0.0)
            in_qty = c3.number_input("수량", min_value=0)
            
            cc1, cc2, cc3 = st.columns(3)
            in_sl = cc1.number_input("손절가 (%)", value=-10.0)
            in_tp1 = cc2.number_input("1차 익절 (%)", value=20.0)
            in_tp_f = cc3.number_input("최종 익절 (%)", value=50.0)
            
            in_date = st.date_input("매수일자", value=datetime.now())
            in_log = st.text_area("매매일지")
            
            if st.button("포트폴리오에 추가", use_container_width=True):
                if in_name and in_buy > 0:
                    ticker = get_ticker_from_name(in_name)
                    if add_to_portfolio(in_name, ticker, in_buy, in_qty, in_sl, in_tp1, in_tp_f, in_date, in_log):
                        st.success(f"{in_name} 등록 완료!")
                        st.rerun()

        portfolio = get_portfolio_from_db()
        if portfolio:
            display_data = []
            total_cost, total_eval = 0, 0
            
            for item in portfolio:
                ticker = item.get('ticker', '')
                curr, _, _ = get_finance_data(ticker)
                buy = float(item.get('buy_price', 0))
                qty = int(item.get('quantity', 0))
                
                cost = buy * qty
                eval_v = curr * qty
                gain = eval_v - cost
                gain_pct = (gain / cost * 100) if cost > 0 else 0
                
                total_cost += cost
                total_eval += eval_v
                
                display_data.append({
                    "종목": item.get('name'),
                    "현재가": curr,
                    "수익률": gain_pct,
                    "수익금": gain,
                    "ID": item['id']
                })
            
            # 요약 지표
            s1, s2, s3 = st.columns(3)
            s1.metric("총 매수", f"{total_cost:,.0f}원")
            s2.metric("총 평가", f"{total_eval:,.0f}원")
            total_pct = (total_eval/total_cost - 1)*100 if total_cost > 0 else 0
            s3.metric("누적 수익률", f"{total_pct:+.2f}%", f"{total_eval-total_cost:,.0f}원")
            
            df = pd.DataFrame(display_data)
            st.dataframe(df.drop(columns=["ID"]), use_container_width=True, hide_index=True)
            
            with st.expander("🗑️ 종목 삭제"):
                del_name = st.selectbox("삭제할 종목 선택", df['종목'].tolist())
                if st.button("선택 종목 삭제"):
                    target_id = df[df['종목'] == del_name]['ID'].values[0]
                    if delete_from_portfolio(target_id):
                        st.warning("삭제되었습니다.")
                        st.rerun()
        else:
            st.info("등록된 종목이 없습니다.")

    with col_chart:
        st.subheader("🔍 종목 심층 분석")
        analysis_name = st.text_input("분석 종목 입력", value="삼성전자")
        analysis_ticker = get_ticker_from_name(analysis_name)
        
        st.write(f"**분석 티커:** `{analysis_ticker}`")
        
        info = get_info_data(analysis_ticker)
        if info:
            f1, f2 = st.columns(2)
            f1.metric("시가총액", f"{info['marketCap']/10**8:,.0f} 억" if info['marketCap'] else "-")
            f1.metric("PBR", f"{info['priceToBook']:.2f}")
            f2.metric("ROE", f"{info['returnOnEquity']*100:.2f}%" if info['returnOnEquity'] else "-")
            f2.metric("배당수익률", f"{info['dividendYield']*100:.2f}%" if info['dividendYield'] else "-")
            
            with st.expander("📝 기업 개요"):
                st.write(info['longBusinessSummary'])
        
        chart_df = get_chart_data(analysis_ticker, analysis_name)
        if not chart_df.empty:
            st.line_chart(chart_df)
