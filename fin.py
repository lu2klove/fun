import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
from google.cloud import firestore
from google.oauth2 import service_account
import json

# --- 1. 페이지 설정 ---
st.set_page_config(
    page_title="Global Financial Dashboard V1.1",
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

def add_to_portfolio(name, ticker, buy_price, quantity, stop_loss_pct, take_profit_1, take_profit_final):
    if db is None: return False
    try:
        db.collection(COLLECTION_NAME).add({
            "name": name, 
            "ticker": ticker, 
            "buy_price": float(buy_price), 
            "quantity": int(quantity),
            "stop_loss_pct": float(stop_loss_pct),
            "tp1_pct": float(take_profit_1),
            "tp_final_pct": float(take_profit_final),
            "created_at": datetime.now()
        })
        return True
    except Exception as e:
        st.error(f"저장 오류: {e}")
        return False

def update_portfolio(doc_id, buy_price, quantity, sl_pct, tp1_pct, tpf_pct):
    if db is None: return False
    try:
        db.collection(COLLECTION_NAME).document(doc_id).update({
            "buy_price": float(buy_price),
            "quantity": int(quantity),
            "stop_loss_pct": float(sl_pct),
            "tp1_pct": float(tp1_pct),
            "tp_final_pct": float(tpf_pct),
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
        yt = yf.Ticker(ticker)
        data = yt.history(period="5d")
        if not data.empty and len(data) >= 2:
            price = data['Close'].iloc[-1]
            prev_price = data['Close'].iloc[-2]
            change = price - prev_price
            change_pct = (change / prev_price) * 100
            return price, change, change_pct
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
            "marketCap": info.get('marketCap', 0),
            "forwardPE": info.get('forwardPE', 0),
            "trailingPE": info.get('trailingPE', 0),
            "priceToBook": info.get('priceToBook', 0),
            "dividendYield": info.get('dividendYield', 0),
            "returnOnEquity": info.get('returnOnEquity', 0),
            "longBusinessSummary": info.get('longBusinessSummary', '정보 없음')
        }
    except:
        return None

# --- 5. 회사명-티커 변환 ---
COMPANY_TICKER_MAP = {
    "삼성전자": "005930.KS", "SK하이닉스": "000660.KS", "네이버": "035420.KS",
    "카카오": "035720.KS", "현대차": "005380.KS", "애플": "AAPL", "테슬라": "TSLA",
    "엔비디아": "NVDA", "비트코인": "BTC-USD", "S&P500": "^GSPC", "나스닥": "^IXIC",
    "코스피": "^KS11", "코스닥": "^KQ11", "원달러환율": "KRW=X", "WTI유": "CL=F"
}

def get_ticker_from_name(name):
    clean = name.strip().replace(" ", "")
    return COMPANY_TICKER_MAP.get(clean, clean.upper())

# --- 6. UI 구성 ---
st.title("📊 글로벌 경제 통합 대시보드")
st.caption(f"버전: 2026-04-08 V1.1 (Final) | DB: richfin | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# --- Requirement 1: 최상단 주가 지표 확장 및 기간별 차트 ---
st.subheader("🌐 주요 시장 지표")
indices_list = [
    ("^KS11", "KOSPI"), ("^KQ11", "KOSDAQ"), 
    ("^IXIC", "NASDAQ"), ("^GSPC", "S&P500"),
    ("KRW=X", "USD/KRW"), ("BTC-USD", "Bitcoin"), ("CL=F", "WTI Oil")
]

top_period = st.radio("지표 차트 기간 선택", ["1d", "1mo", "1y"], index=1, horizontal=True)

idx_cols = st.columns(len(indices_list))
for i, (ticker, name) in enumerate(indices_list):
    price, _, pct = get_finance_data(ticker)
    idx_cols[i].metric(name, f"{price:,.2f}", f"{pct:+.2f}%")
    
    mini_df = get_chart_data(ticker, name, top_period)
    if not mini_df.empty:
        idx_cols[i].line_chart(mini_df, height=100)

st.divider()

col_list, col_chart = st.columns([3, 2])

with col_list:
    st.subheader("💼 내 포트폴리오 관리")
    
    with st.expander("➕ 새 종목 등록 (손절/익절 설정 포함)"):
        c1, c2, c3 = st.columns(3)
        in_name = c1.text_input("종목명/티커", key="reg_name")
        in_buy = c2.number_input("평단가", min_value=0.0, key="reg_buy")
        in_qty = c3.number_input("수량", min_value=0, key="reg_qty")
        
        st.write("**익절/손절 목표 설정 (%)**")
        cc1, cc2, cc3 = st.columns(3)
        in_sl = cc1.number_input("손절가 (%)", value=-10.0, step=1.0)
        in_tp1 = cc2.number_input("1차 익절 (%)", value=50.0, step=5.0)
        in_tp_f = cc3.number_input("최종 익절 (%)", value=100.0, step=10.0)
        
        if st.button("포트폴리오에 등록", use_container_width=True):
            if in_name and in_buy > 0:
                ticker = get_ticker_from_name(in_name)
                if add_to_portfolio(in_name, ticker, in_buy, in_qty, in_sl, in_tp1, in_tp_f):
                    st.success(f"'{in_name}' 등록 완료!")
                    st.rerun()

    portfolio = get_portfolio_from_db()
    display_data = []
    
    if portfolio:
        total_cost, total_eval = 0, 0
        
        for item in portfolio:
            ticker = item.get('ticker', '')
            curr, _, _ = get_finance_data(ticker)
            if curr == 0: curr = float(item.get('buy_price', 0))
                
            buy = float(item.get('buy_price', 0))
            qty = int(item.get('quantity', 0))
            sl_pct = float(item.get('stop_loss_pct', -10))
            tp1_pct = float(item.get('tp1_pct', 50))
            tpf_pct = float(item.get('tp_final_pct', 100))
            
            cost = buy * qty
            eval_v = curr * qty
            gain = eval_v - cost
            gain_pct = (gain / cost * 100) if cost > 0 else 0
            
            total_cost += cost
            total_eval += eval_v
            
            sl_price = buy * (1 + sl_pct/100)
            tp1_price = buy * (1 + tp1_pct/100)
            tpf_price = buy * (1 + tpf_pct/100)
            
            display_data.append({
                "종목": item.get('name', 'N/A'),
                "현재가": curr,
                "수익률": gain_pct,
                "수익금": gain,
                "손절가": sl_price,
                "sl_pct": sl_pct,
                "1차목표": tp1_price,
                "tp1_pct": tp1_pct,
                "최종목표": tpf_price,
                "tpf_pct": tpf_pct,
                "ID": item['id'],
                "Raw": item
            })
            
        if display_data:
            s1, s2, s3 = st.columns(3)
            s1.metric("총 매수", f"{total_cost:,.0f}원")
            s2.metric("총 평가", f"{total_eval:,.0f}원")
            total_pct = (total_eval/total_cost - 1)*100 if total_cost > 0 else 0
            s3.metric("누적 수익률", f"{total_pct:+.2f}%", f"{total_eval-total_cost:,.0f}원")
            
            # --- 테이블 출력용 데이터프레임 생성 (불필요 컬럼 미리 제거) ---
            full_df = pd.DataFrame(display_data)
            df_to_show = full_df.drop(columns=["ID", "Raw", "sl_pct", "tp1_pct", "tpf_pct"])

            # --- 테이블 스타일링 함수 ---
            def style_portfolio(row):
                # row는 출력용 df의 행이므로, 컬럼명을 직접 사용하여 안전하게 접근
                gain_val = row['수익금']
                if gain_val > 0:
                    gain_color = 'color: #ff4b4b;'
                elif gain_val < 0:
                    gain_color = 'color: #1c83e1;'
                else:
                    gain_color = 'color: #31333f;'
                
                # 각 셀별 스타일 정의
                styles = [''] * len(row)
                col_indices = {col: i for i, col in enumerate(row.index)}
                
                if "수익률" in col_indices: styles[col_indices["수익률"]] = gain_color
                if "수익금" in col_indices: styles[col_indices["수익금"]] = gain_color
                if "손절가" in col_indices: styles[col_indices["손절가"]] = 'color: #1c83e1; font-weight: bold;'
                if "1차목표" in col_indices: styles[col_indices["1차목표"]] = 'color: #28a745; font-weight: bold;'
                if "최종목표" in col_indices: styles[col_indices["최종목표"]] = 'color: #28a745; font-weight: bold;'
                
                return styles

            # 스타일러 적용
            st.dataframe(
                df_to_show.style.apply(style_portfolio, axis=1)
                .format({
                    "현재가": "{:,.0f}",
                    "수익률": "{:+.2f}%",
                    "수익금": "{:,.0f}"
                })
                # 복합 문자열 포맷팅 (원본 full_df의 데이터를 참조)
                .format(lambda val: f"{val:,.0f} ({full_df.loc[full_df['손절가'] == val, 'sl_pct'].values[0]:.0f}%)", subset=["손절가"])
                .format(lambda val: f"{val:,.0f} ({full_df.loc[full_df['1차목표'] == val, 'tp1_pct'].values[0]:.0f}%)", subset=["1차목표"])
                .format(lambda val: f"{val:,.0f} ({full_df.loc[full_df['최종목표'] == val, 'tpf_pct'].values[0]:.0f}%)", subset=["최종목표"]),
                use_container_width=True, 
                hide_index=True
            )
            
            with st.expander("🛠️ 종목 정보 수정 및 삭제"):
                selected_name = st.selectbox("수정/삭제할 종목 선택", full_df['종목'].tolist())
                selected_item_raw = next(d['Raw'] for d in display_data if d['종목'] == selected_name)
                
                edit_col1, edit_col2 = st.columns(2)
                new_buy = edit_col1.number_input("수정 평단가", value=float(selected_item_raw.get('buy_price', 0)))
                new_qty = edit_col2.number_input("수정 수량", value=int(selected_item_raw.get('quantity', 0)))
                
                edit_sl_col, edit_tp1_col, edit_tpf_col = st.columns(3)
                new_sl = edit_sl_col.number_input("수정 손절 (%)", value=float(selected_item_raw.get('stop_loss_pct', -10)))
                new_tp1 = edit_tp1_col.number_input("수정 1차익절 (%)", value=float(selected_item_raw.get('tp1_pct', 50)))
                new_tpf = edit_tpf_col.number_input("수정 최종익절 (%)", value=float(selected_item_raw.get('tp_final_pct', 100)))
                
                btn_edit, btn_del = st.columns(2)
                if btn_edit.button("💾 변경사항 저장", use_container_width=True):
                    if update_portfolio(selected_item_raw['id'], new_buy, new_qty, new_sl, new_tp1, new_tpf):
                        st.success("수정되었습니다.")
                        st.rerun()
                
                if btn_del.button("🗑️ 종목 삭제", use_container_width=True, type="secondary"):
                    if delete_from_portfolio(selected_item_raw['id']):
                        st.warning("삭제되었습니다.")
                        st.rerun()
    else:
        st.info("포트폴리오가 비어있습니다. 종목을 추가해 주세요.")

with col_chart:
    st.subheader("🔍 종목 심층 분석")
    analysis_options = [d['종목'] for d in display_data] if display_data else ["삼성전자", "애플", "테슬라"]
    analysis_name = st.selectbox("분석 종목", analysis_options)
    analysis_ticker = get_ticker_from_name(analysis_name)
    
    period = st.select_slider("차트 기간", options=["1mo", "3mo", "6mo", "1y", "2y", "5y"], value="1mo")
    chart_df = get_chart_data(analysis_ticker, analysis_name, period)
    if not chart_df.empty:
        st.line_chart(chart_df)

    st.write("---")
    st.write("🧮 **수익 시뮬레이션**")
    sim_target = st.number_input("목표가 입력", value=0.0, step=100.0)
    if sim_target > 0 and portfolio:
        my_item = next((item for item in portfolio if item.get('name') == analysis_name), None)
        if my_item:
            b_p = float(my_item.get('buy_price', 0))
            q_v = int(my_item.get('quantity', 0))
            p_gain = (sim_target - b_p) * q_v
            p_pct = (sim_target / b_p - 1) * 100 if b_p > 0 else 0
            st.success(f"예상 수익금: **{p_gain:,.0f}원** ({p_pct:+.2f}%)")

    st.write("---")
    st.write("📊 **펀더멘털 & 벨류에이션**")
    info = get_info_data(analysis_ticker)
    if info:
        f1, f2 = st.columns(2)
        m_cap = info['marketCap'] / 10**8 if info['marketCap'] else 0
        f1.write(f"**시가총액:** {m_cap:,.1f} 억")
        f1.write(f"**PER(FWD):** {info['forwardPE']:.2f}")
        f1.write(f"**PBR:** {info['priceToBook']:.2f}")
        
        f2.write(f"**배당수익률:** {info['dividendYield']*100:.2f}%" if info['dividendYield'] else "**배당수익률:** -")
        f2.write(f"**ROE:** {info['returnOnEquity']*100:.2f}%" if info['returnOnEquity'] else "**ROE:** -")
        f2.write(f"**PER(Trail):** {info['trailingPE']:.2f}")
        
        with st.expander("📝 기업 개요"):
            st.write(info['longBusinessSummary'])
    else:
        st.warning("이 종목의 상세 정보를 가져올 수 없습니다.")

st.sidebar.title("System Info")
if st.sidebar.button("♻️ DB 초기화 & 캐시삭제"):
    st.cache_resource.clear()
    st.cache_data.clear()
    st.rerun()

st.sidebar.info(f"Connected: richfin\nVersion: V1.1")
