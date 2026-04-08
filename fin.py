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

# --- 2. Firestore 데이터베이스 초기화 및 인증 ---
@st.cache_resource
def init_db():
    try:
        if "firebase" in st.secrets:
            if "text_key" in st.secrets["firebase"]:
                raw_json = st.secrets["firebase"]["text_key"]
                processed_json = raw_json.replace("\\\\n", "\n").replace("\\n", "\n")
                
                try:
                    key_dict = json.loads(processed_json, strict=False)
                except json.JSONDecodeError:
                    cleaned_json = processed_json.replace('\n', '\\n').replace('\r', '\\r')
                    key_dict = json.loads(cleaned_json, strict=False)
                
                if "private_key" in key_dict:
                    key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n").strip()
                
                creds = service_account.Credentials.from_service_account_info(key_dict)
                
                # 사용자가 생성한 'richfin' 데이터베이스 ID 사용
                client = firestore.Client(
                    credentials=creds, 
                    project=key_dict.get('project_id'),
                    database="richfin"
                )
                return client
        return None
    except Exception as e:
        st.error(f"인증 오류 발생: {e}")
        return None

db = init_db()
COLLECTION_NAME = "my_portfolio"

# --- 3. DB 핸들링 함수 ---
def get_portfolio_from_db():
    if db is None: return []
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        results = [{"id": d.id, **d.to_dict()} for d in docs]
        results.sort(key=lambda x: x.get('created_at', datetime.min), reverse=True)
        return results
    except Exception as e:
        st.warning(f"데이터 로드 오류: {e}")
        return []

def add_to_portfolio(name, ticker, buy_price, quantity):
    if db is None: return False
    try:
        db.collection(COLLECTION_NAME).add({
            "name": name, 
            "ticker": ticker, 
            "buy_price": float(buy_price), 
            "quantity": int(quantity), 
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
        yt = yf.Ticker(ticker)
        data = yt.history(period="2d")
        if not data.empty and len(data) >= 2:
            price = data['Close'].iloc[-1]
            prev_price = data['Close'].iloc[-2]
            change = price - prev_price
            change_pct = (change / prev_price) * 100
            return price, change, change_pct
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
        data = yt.history(period=period)
        if not data.empty:
            df = data[['Close']].copy()
            df.columns = [name]
            return df
    except:
        return pd.DataFrame()

# --- 5. 회사명-티커 변환 ---
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
st.caption(f"DB: richfin | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# 메인 지표 레이아웃
m1, m2, m3, m4 = st.columns(4)
indices = [
    ("^KS11", "KOSPI"), ("^IXIC", "NASDAQ"), 
    ("BTC-USD", "Bitcoin"), ("KRW=X", "USD/KRW")
]

for col, (ticker, name) in zip([m1, m2, m3, m4], indices):
    price, _, pct = get_finance_data(ticker)
    col.metric(name, f"{price:,.2f}", f"{pct:+.2f}%")

st.divider()

# 변수 초기화 (KeyError 방지)
display_data = []

# 좌측: 포트폴리오 관리 / 우측: 상세 차트
col_list, col_chart = st.columns([3, 2])

with col_list:
    st.subheader("💼 내 포트폴리오")
    with st.expander("➕ 새 종목 등록"):
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        in_name = c1.text_input("종목명", placeholder="삼성전자 또는 AAPL")
        in_buy = c2.number_input("평단가", min_value=0.0)
        in_qty = c3.number_input("수량", min_value=0)
        if c4.button("등록", use_container_width=True):
            if in_name and in_buy > 0:
                ticker = get_ticker_from_name(in_name)
                if add_to_portfolio(in_name, ticker, in_buy, in_qty):
                    st.success("등록 완료")
                    st.rerun()

    portfolio = get_portfolio_from_db()
    if portfolio:
        total_cost, total_eval = 0, 0
        
        for item in portfolio:
            ticker = item.get('ticker', '')
            curr, _, _ = get_finance_data(ticker)
            
            # 가격 정보가 없는 경우 예외 처리
            if curr == 0:
                curr = float(item.get('buy_price', 0))
                
            buy = float(item.get('buy_price', 0))
            qty = int(item.get('quantity', 0))
            
            cost = buy * qty
            eval_v = curr * qty
            gain = eval_v - cost
            gain_pct = (gain / cost * 100) if cost > 0 else 0
            
            total_cost += cost
            total_eval += eval_v
            
            display_data.append({
                "종목": item.get('name', 'N/A'),
                "수량": qty,
                "평단가": f"{buy:,.0f}",
                "현재가": f"{curr:,.0f}",
                "수익률": f"{gain_pct:+.2f}%",
                "수익금": f"{gain:,.0f}",
                "ID": item['id']
            })
            
        if display_data:
            # 요약 메트릭
            s1, s2, s3 = st.columns(3)
            s1.metric("총 매수", f"{total_cost:,.0f}원")
            s2.metric("총 평가", f"{total_eval:,.0f}원")
            total_pct = (total_eval/total_cost - 1)*100 if total_cost > 0 else 0
            s3.metric("전체 수익률", f"{total_pct:+.2f}%", f"{total_eval-total_cost:,.0f}원")
            
            df = pd.DataFrame(display_data)
            st.dataframe(df.drop(columns="ID"), use_container_width=True, hide_index=True)
            
            with st.expander("🗑️ 종목 삭제"):
                target = st.selectbox("삭제할 종목", df['종목'].tolist())
                if st.button("삭제 실행"):
                    doc_id = df[df['종목'] == target]['ID'].values[0]
                    if delete_from_portfolio(doc_id): st.rerun()
    else:
        st.info("등록된 종목이 없습니다.")

with col_chart:
    st.subheader("🔍 종목 상세 분석")
    
    # display_data가 비어있을 경우를 대비한 안전한 옵션 리스트 생성
    analysis_options = [d['종목'] for d in display_data] if display_data else ["삼성전자"]
    analysis_name = st.selectbox("분석할 종목 선택", analysis_options)
    analysis_ticker = get_ticker_from_name(analysis_name)
    
    period = st.select_slider("기간", options=["1mo", "3mo", "6mo", "1y"], value="1mo")
    chart_df = get_chart_data(analysis_ticker, analysis_name, period)
    if not chart_df.empty:
        st.line_chart(chart_df)
    else:
        st.warning("차트 데이터를 불러올 수 없습니다. 티커를 확인해 주세요.")
    
    # 간이 계산기
    st.write("---")
    st.write("🧮 **수익 시뮬레이션**")
    target_price = st.number_input("목표가 설정", value=0.0)
    if target_price > 0 and portfolio:
        # 선택한 종목의 평단가 찾기
        my_item = next((item for item in portfolio if item.get('name') == analysis_name), None)
        if my_item:
            buy_p = float(my_item.get('buy_price', 0))
            qty_v = int(my_item.get('quantity', 0))
            proj_gain = (target_price - buy_p) * qty_v
            proj_pct = (target_price / buy_p - 1) * 100 if buy_p > 0 else 0
            st.success(f"목표가 도달 시 예상 수익: **{proj_gain:,.0f}원** ({proj_pct:+.2f}%)")

# 사이드바
st.sidebar.title("환경 설정")
if st.sidebar.button("♻️ DB 연결 초기화"):
    st.cache_resource.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.write(f"프로젝트: rich-54943")
st.sidebar.write(f"DB ID: richfin")
