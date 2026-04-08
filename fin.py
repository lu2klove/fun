import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
from google.cloud import firestore
from google.oauth2 import service_account
import json
import re

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
        # Streamlit secrets에서 설정 가져오기
        if "firebase" in st.secrets:
            raw_json = st.secrets["firebase"]["text_key"]
            
            # --- [수정 포인트] JSON 파싱 전 원시 문자열 단계에서 개행 처리 ---
            # r"\\n" (텍스트 그대로의 \n)을 실제 줄바꿈 문자 "\n"으로 변경
            # 일부 OS나 편집기 환경에서 발생하는 이중 이스케이프 문제를 해결합니다.
            processed_json = raw_json.replace("\\\\n", "\n").replace("\\n", "\n")
            
            try:
                # 1. 정제된 문자열로 JSON 로드
                key_dict = json.loads(processed_json, strict=False)
            except json.JSONDecodeError:
                # 2. 실패 시 제어 문자 클리닝 후 재시도
                cleaned_json = processed_json.replace('\n', '\\n').replace('\r', '\\r')
                key_dict = json.loads(cleaned_json, strict=False)

            # --- PEM 파일 로드 오류(InvalidByte) 해결을 위한 최종 검증 ---
            if "private_key" in key_dict:
                pk = key_dict["private_key"]
                # 다시 한번 pk 내부의 문자열을 정제 (불필요한 공백 제거)
                key_dict["private_key"] = pk.strip()

            creds = service_account.Credentials.from_service_account_info(key_dict)
            client = firestore.Client(credentials=creds, project=key_dict['project_id'])
            return client
        else:
            st.error("Secrets 설정에서 'firebase' 정보를 찾을 수 없습니다.")
            return None
    except Exception as e:
        st.error(f"DB 연결 중 오류 발생: {e}")
        st.info("💡 **여전히 오류가 발생한다면?**")
        st.markdown("""
        1. Google Cloud 콘솔에서 다운로드한 **JSON 파일**을 메모장으로 여세요.
        2. "private_key" 항목의 값(-----BEGIN...부터 ...END-----\\n까지)만 따로 복사하세요.
        3. 아래와 같이 `secrets.toml`에 직접 입력해 보세요:
        ```toml
        [firebase]
        project_id = "당신의_프로젝트_ID"
        private_key = \"\"\"-----BEGIN PRIVATE KEY-----
        (여기에 줄바꿈이 포함된 실제 키 내용 붙여넣기)
        -----END PRIVATE KEY-----\"\"\"
        client_email = "서비스_계정_이메일"
        ```
        """)
        return None

db = init_db()
COLLECTION_NAME = "my_portfolio"

# --- 3. DB 핸들링 함수 ---
def get_portfolio_from_db():
    if db is None:
        return []
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        results = [{"id": d.id, **d.to_dict()} for d in docs]
        # 수동 정렬 (DB 인덱스 오류 방지)
        results.sort(key=lambda x: x.get('created_at', datetime.min), reverse=True)
        return results
    except Exception as e:
        st.warning(f"데이터를 불러오는 중 문제가 발생했습니다: {e}")
        return []

def add_to_portfolio(name, ticker, buy_price, quantity):
    if db is None:
        st.error("데이터베이스에 연결되어 있지 않습니다.")
        return False
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
        st.error(f"Firestore 쓰기 오류: {e}")
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

with st.expander("➕ 새 종목 등록하기", expanded=True):
    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
    in_name = c1.text_input("종목명 (또는 티커)", placeholder="예: 삼성전자")
    in_buy = c2.number_input("평단가", min_value=0.0, step=100.0, format="%.2f")
    in_qty = c3.number_input("수량", min_value=0, step=1)
    
    if c4.button("등록"):
        if in_name and in_buy > 0 and in_qty > 0:
            ticker = get_ticker_from_name(in_name)
            with st.spinner('등록 중...'):
                success = add_to_portfolio(in_name, ticker, in_buy, in_qty)
                if success:
                    st.success(f"'{in_name}'({ticker}) 등록에 성공했습니다!")
                    st.rerun()
        else:
            st.warning("종목 정보(이름, 평단가, 수량)를 모두 입력해주세요.")

# DB에서 목록 불러오기
portfolio = get_portfolio_from_db()

if portfolio:
    data_list = []
    total_cost, total_eval = 0, 0
    
    with st.spinner('실시간 포트폴리오 분석 중...'):
        for item in portfolio:
            ticker = item.get('ticker', '')
            if not ticker: continue
            
            curr, _, _ = get_finance_data(ticker)
            buy_price = float(item.get('buy_price', 0))
            quantity = int(item.get('quantity', 0))
            
            cost = buy_price * quantity
            eval_v = curr * quantity
            total_cost += cost
            total_eval += eval_v
            
            gain = eval_v - cost
            gain_pct = (gain / cost * 100) if cost > 0 else 0
            
            data_list.append({
                "종목": item.get('name', 'N/A'),
                "티커": ticker,
                "수량": quantity,
                "평단가": f"{buy_price:,.0f}",
                "현재가": f"{curr:,.0f}",
                "수익금": f"{gain:,.0f}",
                "수익률": f"{gain_pct:+.2f}%",
                "ID": item['id']
            })

    if data_list:
        s1, s2, s3 = st.columns(3)
        s1.metric("총 매수금액", f"{total_cost:,.0f}원")
        s2.metric("총 평가금액", f"{total_eval:,.0f}원")
        total_gain_pct = (total_eval / total_cost - 1) * 100 if total_cost > 0 else 0
        s3.metric("총 손익", f"{total_eval-total_cost:,.0f}원", f"{total_gain_pct:+.2f}%")

        df_p = pd.DataFrame(data_list)
        st.dataframe(df_p.drop(columns="ID"), use_container_width=True)

        with st.expander("🗑️ 종목 삭제"):
            del_target = st.selectbox("삭제할 종목 선택", df_p['종목'].tolist())
            if st.button("선택한 종목 삭제"):
                doc_id = df_p[df_p['종목'] == del_target]['ID'].values[0]
                if delete_from_portfolio(doc_id):
                    st.success("삭제되었습니다.")
                    st.rerun()
    else:
        st.info("포트폴리오 데이터를 가공할 수 없습니다.")
else:
    st.info("등록된 종목이 없습니다. 위 '새 종목 등록하기' 메뉴에서 종목을 추가해 보세요.")

st.divider()

# 3. 종목 계산기 및 상세 분석
st.subheader("🧮 종목 계산기 & 🔍 상세 분석")
calc_col1, calc_col2 = st.columns([1, 2])

with calc_col1:
    st.write("📌 **계산기 입력**")
    calc_name = st.text_input("분석할 종목명", placeholder="예: 삼성전자", key="calc_name_input")
    c_price = 0.0
    if calc_name:
        c_ticker = get_ticker_from_name(calc_name)
        c_price, _, _ = get_finance_data(c_ticker)
        st.info(f"현재 시세: {c_price:,.2f}")

    b_price = st.number_input("구매 가격", value=float(c_price) if c_price > 0 else 0.0, key="calc_buy_price")
    qty = st.number_input("보유 수량 ", value=0, key="calc_qty")
    
    p_c1, p_c2 = st.columns(2)
    sl_pct = p_c1.number_input("손절 (%)", value=10.0, key="calc_sl_pct")
    tp_pct = p_c2.number_input("익절 (%)", value=20.0, key="calc_tp_pct")

with calc_col2:
    if b_price > 0 and qty > 0:
        total_inv = b_price * qty
        sl_price = b_price * (1 - sl_pct/100)
        tp_price = b_price * (1 + tp_pct/100)
        
        st.write(f"💰 **투자 요약: {total_inv:,.0f}원**")
        g1, g2 = st.columns(2)
        g1.error(f"📉 손절가: {sl_price:,.0f}")
        g2.success(f"📈 익절가: {tp_price:,.0f}")
        
        if calc_name:
            st.write("---")
            st.write(f"🔍 **{calc_name} 주요 지표**")
            try:
                stock_info = yf.Ticker(get_ticker_from_name(calc_name)).info
                f1, f2, f3 = st.columns(3)
                f1.metric("PER", f"{stock_info.get('trailingPE', 'N/A')}")
                f2.metric("PBR", f"{stock_info.get('priceToBook', 'N/A')}")
                f3.metric("배당수익률", f"{stock_info.get('dividendYield', 0)*100:.2f}%" if stock_info.get('dividendYield') else "0%")
            except:
                st.write("상세 지표를 가져올 수 없습니다.")
    else:
        st.info("종목명과 투자 정보를 입력하면 가이드와 상세 지표가 표시됩니다.")

# 사이드바
if st.sidebar.button("전체 새로고침"):
    st.rerun()
st.sidebar.markdown("---")
st.sidebar.info("💡 **Firestore DB 상태:** 연결됨" if db else "⚠️ **Firestore DB 상태:** 연결 안 됨")
