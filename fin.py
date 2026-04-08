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
    page_title="Global Financial Dashboard V1.8",
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
        if not ticker: return None
        yt = yf.Ticker(ticker)
        info = yt.info
        if not info or len(info) < 5: return None
        return {
            "marketCap": info.get('marketCap') or info.get('totalAssets') or 0,
            "forwardPE": info.get('forwardPE') or info.get('trailingPE') or 0,
            "priceToBook": info.get('priceToBook') or 0,
            "dividendYield": info.get('dividendYield') or 0,
            "returnOnEquity": info.get('returnOnEquity') or 0,
            "longBusinessSummary": info.get('longBusinessSummary') or '정보 없음'
        }
    except:
        return None

# --- 5. 티커 변환 로직 ---
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
st.title("📊 글로벌 경제 통합 대시보드")
st.caption(f"버전: 2026-04-08 V1.2 | DB: richfin | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

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
    
    top_period = st.radio("차트 기간", ["1d", "1mo", "1y"], index=1, horizontal=True)
    
    # 7개 지표를 표시하기 위해 컬럼 생성
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
        
        with st.expander("➕ 새 종목 등록"):
            c1, c2, c3 = st.columns(3)
            in_name = c1.text_input("종목명", key="reg_name")
            in_buy = c2.number_input("평단가", min_value=0.0)
            in_qty = c3.number_input("수량", min_value=0)
            cc1, cc2, cc3 = st.columns(3)
            in_sl = cc1.number_input("손절가 (%)", value=-10.0)
            in_tp1 = cc2.number_input("1차 익절 (%)", value=20.0)
            in_tp_f = cc3.number_input("최종 익절 (%)", value=50.0)
            in_date = st.date_input("매수일자", value=datetime.now())
            in_log = st.text_area("매매일지")
            if st.button("포트폴리오 추가", use_container_width=True):
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

            # --- 테이블 스타일링 함수 ---
            def apply_custom_style(row):
                styles = [''] * len(row)
                col_map = {col: i for i, col in enumerate(row.index)}
                
                # 수익률/수익금 색상
                gain_val = row['수익률']
                color = 'color: #ff4b4b;' if gain_val > 0 else ('color: #1c83e1;' if gain_val < 0 else '')
                if '수익률' in col_map: styles[col_map['수익률']] = color
                if '수익금' in col_map: styles[col_map['수익금']] = color
                
                # 손절가: 굵은 파란색
                if '손절가' in col_map: styles[col_map['손절가']] = 'color: #1c83e1; font-weight: bold;'
                
                # 익절 목표: 굵은 녹색
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
        analysis_options = [d['종목'] for d in display_data] if display_data else ["삼성전자", "AAPL", "NVDA"]
        analysis_name = st.selectbox("분석 종목", analysis_options)
        analysis_ticker = get_ticker_from_name(analysis_name)
        
        st.write(f"**티커:** `{analysis_ticker}`")
        
        st.write("📊 **펀더멘털**")
        info = get_info_data(analysis_ticker)
        if info:
            f1, f2 = st.columns(2)
            f1.metric("시가총액", f"{info['marketCap']/10**8:,.1f} 억")
            f1.metric("PBR", f"{info['priceToBook']:.2f}")
            f2.metric("ROE", f"{info['returnOnEquity']*100:.2f}%" if info['returnOnEquity'] else "-")
            f2.metric("배당수익률", f"{info['dividendYield']*100:.2f}%" if info['dividendYield'] else "-")
            with st.expander("기업 개요"): st.write(info['longBusinessSummary'])
        else:
            st.warning("데이터 부족")
        
        chart_df = get_chart_data(analysis_ticker, analysis_name, "1mo")
        if not chart_df.empty: st.line_chart(chart_df)

st.sidebar.button("♻️ 초기화", on_click=lambda: (st.cache_resource.clear(), st.cache_data.clear()))
