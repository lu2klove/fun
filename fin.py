import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
from google.cloud import firestore
from google.oauth2 import service_account
import json
import requests
import re

# --- 1. 페이지 설정 ---
st.set_page_config(
    page_title="Global Financial Dashboard V2.0",
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

def update_portfolio(doc_id, buy_price, quantity, sl_pct, tp1_pct, tpf_pct, buy_date, trading_log):
    if db is None: return False
    try:
        db.collection(COLLECTION_NAME).document(doc_id).update({
            "buy_price": float(buy_price),
            "quantity": int(quantity),
            "stop_loss_pct": float(sl_pct),
            "tp1_pct": float(tp1_pct),
            "tp_final_pct": float(tpf_pct),
            "buy_date": datetime.combine(buy_date, datetime.min.time()) if isinstance(buy_date, (datetime, pd.Timestamp)) else datetime.now(),
            "trading_log": trading_log,
            "updated_at": datetime.now()
        })
        return True
    except Exception as e:
        st.error(f"수정 오류: {e}")
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
        if not data.empty and len(data) >= 2:
            price = data['Close'].iloc[-1]
            prev_price = data['Close'].iloc[-2]
            change = price - prev_price
            change_pct = (change / prev_price) * 100
            return float(price), float(change), float(change_pct)
    except:
        pass
    return 0.0, 0.0, 0.0

@st.cache_data(ttl=300)
def get_chart_data(ticker, name, period="1mo"):
    try:
        yt = yf.Ticker(ticker)
        interval = "5m" if period == "1d" else "1d"
        data = yt.history(period=period, interval=interval)
        if not data.empty:
            df = data[['Close']].copy()
            df.columns = [name]
            return df
    except:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_info_data(ticker):
    try:
        if not ticker: return None
        yt = yf.Ticker(ticker)
        info = yt.info
        if not info or len(info) < 5: return None
        return info 
    except:
        return None

# --- 5. 티커 변환 및 검증 로직 ---
COMPANY_TICKER_MAP = {
    "삼성전자": "005930.KS", "SK하이닉스": "000660.KS", "네이버": "035420.KS",
    "카카오": "035720.KS", "현대차": "005380.KS", "애플": "AAPL", "테슬라": "TSLA",
    "엔비디아": "NVDA", "비트코인": "BTC-USD", "S&P500": "^GSPC", "나스닥": "^IXIC",
    "에코프로": "086520.KQ", "에코프로비엠": "247540.KQ"
}

def search_ticker_korea(query):
    """네이버 금융 검색을 활용하여 한국 종목 코드를 찾습니다."""
    try:
        # 네이버 금융 종목 검색 API 시뮬레이션
        url = f"https://ac.finance.naver.com/ac?q={query}&q_enc=euc-kr&st=111&frm=stock&r_format=json&r_enc=euc-kr&r_unicode=1&t_koreng=1"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            items = data.get('items', [[]])[0]
            if items:
                # 검색 결과 중 첫 번째 아이템의 코드 추출 (예: ['에코프로', '086520', '...', '...'])
                code = items[0][1]
                # 한국 시장은 .KS(코스피) 또는 .KQ(코스닥)가 필요함. 
                # yfinance에서 둘 다 시도해보거나, 일반적인 패턴으로 접미사 부여
                for suffix in [".KQ", ".KS"]:
                    test_ticker = code + suffix
                    yt = yf.Ticker(test_ticker)
                    if not yt.history(period="1d").empty:
                        return test_ticker
    except:
        pass
    return None

def search_ticker_global(query):
    """야후 파이낸스 검색 API를 사용합니다."""
    try:
        query = re.sub(r'[^a-zA-Z0-9가-힣\s]', '', query)
        if not query.strip(): return None
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get('quotes'):
                return data['quotes'][0]['symbol']
    except:
        pass
    return None

def validate_and_get_ticker(name):
    """종목명을 티커로 변환하고 다중 소스를 통해 유효성을 검증합니다."""
    clean = name.strip()
    if not clean: return None
    
    # 1. 수동 맵핑 확인
    if clean in COMPANY_TICKER_MAP:
        return COMPANY_TICKER_MAP[clean]
    
    # 2. 한국 시장 우선 검색 (한글이 포함된 경우)
    if bool(re.search('[가-힣]', clean)):
        kr_ticker = search_ticker_korea(clean)
        if kr_ticker: return kr_ticker
        
    # 3. 글로벌 검색 (Yahoo Finance)
    ticker_candidate = search_ticker_global(clean)
    
    # 4. 티커 형태 직접 입력 확인
    if not ticker_candidate and clean.replace(".","").replace("-","").isalnum():
        ticker_candidate = clean.upper()
    
    if ticker_candidate:
        try:
            yt = yf.Ticker(ticker_candidate)
            if not yt.history(period="1d").empty:
                return ticker_candidate
        except:
            pass
            
    return None

def get_ticker_from_name(name):
    clean = name.strip()
    if clean in COMPANY_TICKER_MAP: return COMPANY_TICKER_MAP[clean]
    # 상세 페이지용 (이미 검증된 데이터 사용 권장)
    found = validate_and_get_ticker(clean)
    return found if found else clean.upper()

# --- 6. UI 구성 ---
st.title("📊 글로벌 경제 통합 대시보드")
st.caption(f"버전: 2026-04-08 V2.0 | DB: richfin | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if db is None:
    st.error("❌ Firestore 연결에 실패했습니다.")
else:
    # --- 최상단 주요 지표 ---
    st.subheader("🌐 주요 시장 지표")
    indices_list = [
        ("^KS11", "KOSPI"), ("^KQ11", "KOSDAQ"), 
        ("^IXIC", "NASDAQ"), ("^GSPC", "S&P500"),
        ("KRW=X", "USD/KRW"), ("BTC-USD", "Bitcoin"), ("CL=F", "WTI Oil")
    ]
    
    top_period = st.radio("시장 지표 차트 기간", ["1d", "1mo", "1y"], index=1, horizontal=True, key="top_chart_period")
    
    idx_cols = st.columns(len(indices_list))
    for i, (ticker, name) in enumerate(indices_list):
        p, _, pct = get_finance_data(ticker)
        idx_cols[i].metric(name, f"{p:,.2f}", f"{pct:+.2f}%")
        m_df = get_chart_data(ticker, name, top_period)
        if not m_df.empty: 
            idx_cols[i].line_chart(m_df, height=80)

    st.divider()

    col_list, col_chart = st.columns([3, 2])

    with col_list:
        st.subheader("💼 내 포트폴리오 관리")
        
        with st.expander("➕ 새 종목 등록", expanded=True):
            c1, c2, c3 = st.columns(3)
            in_name = c1.text_input("종목명 또는 티커 (예: 삼성전자, 애플, 에코프로)", key="reg_name")
            in_buy = c2.number_input("평단가", min_value=0.0)
            in_qty = c3.number_input("수량", min_value=0)
            cc1, cc2, cc3 = st.columns(3)
            in_sl = cc1.number_input("손절가 (%)", value=-10.0)
            in_tp1 = cc2.number_input("1차 익절 (%)", value=20.0)
            in_tp_f = cc3.number_input("최종 익절 (%)", value=50.0)
            in_date = st.date_input("매수일자", value=datetime.now())
            in_log = st.text_area("매매일지")
            
            if st.button("포트폴리오 추가", use_container_width=True):
                if not in_name:
                    st.warning("종목명을 입력해주세요.")
                elif in_buy <= 0:
                    st.warning("유효한 평단가를 입력해주세요.")
                else:
                    with st.spinner(f"'{in_name}' 유효성 검증 및 데이터 매핑 중..."):
                        valid_ticker = validate_and_get_ticker(in_name)
                    
                    if valid_ticker:
                        if add_to_portfolio(in_name, valid_ticker, in_buy, in_qty, in_sl, in_tp1, in_tp_f, in_date, in_log):
                            st.success(f"✅ {in_name} ({valid_ticker}) 등록 완료!")
                            st.rerun()
                    else:
                        st.error(f"❌ '{in_name}' 종목을 찾을 수 없습니다. (한국 종목은 정확한 명칭을, 해외 종목은 티커를 입력해주세요.)")

        portfolio = get_portfolio_from_db()
        if portfolio:
            display_data = []
            total_cost, total_eval = 0, 0
            
            for item in portfolio:
                ticker = item.get('ticker', '')
                curr, _, _ = get_finance_data(ticker)
                if curr == 0: curr = float(item.get('buy_price', 0))
                
                buy = float(item.get('buy_price', 0))
                qty = int(item.get('quantity', 0))
                cost = buy * qty
                eval_v = curr * qty
                gain = eval_v - cost
                gain_pct = (gain / cost * 100) if cost > 0 else 0
                
                total_cost += cost
                total_eval += eval_v
                
                sl_p = buy * (1 + float(item.get('stop_loss_pct', -10))/100)
                tp1_p = buy * (1 + float(item.get('tp1_pct', 20))/100)
                tpf_p = buy * (1 + float(item.get('tp_final_pct', 50))/100)
                
                display_data.append({
                    "종목": item.get('name'),
                    "티커": ticker,
                    "평단가": buy,
                    "수익률": gain_pct,
                    "수익금": gain,
                    "손절가": sl_p,
                    "1차목표": tp1_p,
                    "최종목표": tpf_p,
                    "ID": item['id'],
                    "Raw": item
                })
            
            s1, s2, s3 = st.columns(3)
            s1.metric("총 매수", f"{total_cost:,.0f}원")
            s2.metric("총 평가", f"{total_eval:,.0f}원")
            total_pct = (total_eval/total_cost - 1)*100 if total_cost > 0 else 0
            s3.metric("누적 수익률", f"{total_pct:+.2f}%", f"{total_eval-total_cost:,.0f}원")
            
            full_df = pd.DataFrame(display_data)
            df_to_show = full_df.drop(columns=["ID", "Raw"])

            def apply_custom_style(row):
                styles = [''] * len(row)
                col_map = {col: i for i, col in enumerate(row.index)}
                gain_val = row['수익률']
                color = 'color: #ff4b4b;' if gain_val > 0 else ('color: #1c83e1;' if gain_val < 0 else '')
                if '수익률' in col_map: styles[col_map['수익률']] = color
                if '수익금' in col_map: styles[col_map['수익금']] = color
                if '손절가' in col_map: styles[col_map['손절가']] = 'color: #1c83e1; font-weight: bold;'
                green_bold = 'color: #28a745; font-weight: bold;'
                if '1차목표' in col_map: styles[col_map['1차목표']] = green_bold
                if '최종목표' in col_map: styles[col_map['최종목표']] = green_bold
                return styles

            st.dataframe(
                df_to_show.style.apply(apply_custom_style, axis=1).format({
                    "평단가": "{:,.0f}",
                    "수익률": "{:+.2f}%",
                    "수익금": "{:,.0f}",
                    "손절가": "{:,.0f}",
                    "1차목표": "{:,.0f}",
                    "최종목표": "{:,.0f}"
                }),
                use_container_width=True, hide_index=True
            )
            
            with st.expander("🛠️ 종목 상세 정보 수정"):
                selected_name = st.selectbox("수정할 종목", full_df['종목'].tolist())
                sel_item = next(d['Raw'] for d in display_data if d['종목'] == selected_name)
                
                e1, e2 = st.columns(2)
                up_buy = e1.number_input("수정 평단가", value=float(sel_item.get('buy_price', 0)))
                up_qty = e2.number_input("수정 수량", value=int(sel_item.get('quantity', 0)))
                
                es1, es2, es3 = st.columns(3)
                up_sl = es1.number_input("수정 손절 (%)", value=float(sel_item.get('stop_loss_pct', -10)))
                up_tp1 = es2.number_input("수정 1차익절 (%)", value=float(sel_item.get('tp1_pct', 20)))
                up_tpf = es3.number_input("수정 최종익절 (%)", value=float(sel_item.get('tp_final_pct', 50)))
                
                up_log = st.text_area("매매일지 수정", value=sel_item.get('trading_log', ''))
                
                b1, b2 = st.columns(2)
                if b1.button("💾 변경 저장", use_container_width=True):
                    if update_portfolio(sel_item['id'], up_buy, up_qty, up_sl, up_tp1, up_tpf, sel_item.get('buy_date'), up_log):
                        st.success("수정 성공!")
                        st.rerun()
                if b2.button("🗑️ 삭제", use_container_width=True, type="secondary"):
                    if delete_from_portfolio(sel_item['id']):
                        st.warning("삭제됨")
                        st.rerun()
        else:
            st.info("포트폴리오가 비어있습니다.")

    with col_chart:
        st.subheader("🔍 종목 심층 분석")
        analysis_options = [d['종목'] for d in display_data] if display_data else ["삼성전자", "애플", "엔비디아"]
        analysis_name = st.selectbox("분석 종목 선택", analysis_options)
        analysis_ticker = get_ticker_from_name(analysis_name)
        
        chart_period = st.segmented_control("분석 차트 기간", ["1d", "1mo", "1y"], default="1mo")
        
        st.write(f"📌 **티커:** `{analysis_ticker}`")
        
        chart_df = get_chart_data(analysis_ticker, analysis_name, chart_period)
        if not chart_df.empty: 
            st.line_chart(chart_df)
        
        st.markdown("---")
        st.write("🏛️ **상세 펀더멘털 및 가치 지표**")
        info = get_info_data(analysis_ticker)
        if info:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("현재가", f"{info.get('currentPrice', 0):,.2f}")
            m2.metric("PER(Fwd)", f"{info.get('forwardPE', 0):.2f}")
            m3.metric("PBR", f"{info.get('priceToBook', 0):.2f}")
            m4.metric("배당수익률", f"{info.get('dividendYield', 0)*100:.2f}%" if info.get('dividendYield') else "-")
            
            with st.expander("📝 전체 지표 리스트 (상세)", expanded=True):
                fund_data = {
                    "항목": [
                        "시가총액", "PSR (Price/Sales)", "EV/EBITDA", "ROE (자기자본이익률)", 
                        "부채비율 (Debt/Equity)", "매출 성장률 (YoY)", "주당순이익 (EPS)", 
                        "영업이익률", "보유현금", "52주 최고가", "52주 최저가"
                    ],
                    "값": [
                        f"{info.get('marketCap', 0)/10**8:,.1f} 억" if info.get('marketCap') else "-",
                        f"{info.get('priceToSalesTrailing12Months', 0):.2f}" if info.get('priceToSalesTrailing12Months') else "-",
                        f"{info.get('enterpriseToEbitda', 0):.2f}" if info.get('enterpriseToEbitda') else "-",
                        f"{info.get('returnOnEquity', 0)*100:.2f}%" if info.get('returnOnEquity') else "-",
                        f"{info.get('debtToEquity', 0):.2f}" if info.get('debtToEquity') else "-",
                        f"{info.get('revenueGrowth', 0)*100:.2f}%" if info.get('revenueGrowth') else "-",
                        f"{info.get('trailingEps', 0):.2f}" if info.get('trailingEps') else "-",
                        f"{info.get('operatingMargins', 0)*100:.2f}%" if info.get('operatingMargins') else "-",
                        f"{info.get('totalCash', 0)/10**8:,.1f} 억" if info.get('totalCash') else "-",
                        f"{info.get('fiftyTwoWeekHigh', 0):,.2f}",
                        f"{info.get('fiftyTwoWeekLow', 0):,.2f}"
                    ]
                }
                st.table(pd.DataFrame(fund_data))
            
            with st.expander("🏢 기업 상세 개요"): 
                st.write(info.get('longBusinessSummary', '정보가 없습니다.'))
        else:
            st.warning("이 종목의 상세 펀더멘털 데이터를 불러올 수 없습니다.")

st.sidebar.button("♻️ 데이터 초기화", on_click=lambda: (st.cache_resource.clear(), st.cache_data.clear()))
