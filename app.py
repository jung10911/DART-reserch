import streamlit as st
import pandas as pd
import requests
import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
import re

# ==========================================
# 1. API KEY 세팅
# ==========================================
DART_API_KEY = "0d3337714983152206d438906ff525000677118e"
KRX_API_KEY = "E76EEC8AF3D142F2BCA4A0EDB7510FEC9DA32064"

# ==========================================
# 2. 공통 유틸리티 함수
# ==========================================
def safe_float(val):
    if pd.isna(val) or val is None:
        return 0.0
    val_str = str(val).replace(',', '').strip()
    if val_str in ['-', '', 'NaN', 'null']:
        return 0.0
    try:
        return float(val_str)
    except ValueError:
        return 0.0

# ==========================================
# 3. DART 고유번호 맵핑
# ==========================================
@st.cache_data(ttl=86400) 
def load_dart_corp_codes():
    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    params = {'crtfc_key': DART_API_KEY}
    try:
        res = requests.get(url, params=params)
        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            xml_data = z.read('CORPCODE.xml')
        
        tree = ET.fromstring(xml_data)
        corp_dict = {}
        for list_node in tree.findall('list'):
            stock_code = list_node.find('stock_code').text
            if stock_code and stock_code.strip() != '':
                corp_name = list_node.find('corp_name').text.strip()
                corp_code = list_node.find('corp_code').text
                corp_dict[corp_name] = {'corp_code': corp_code, 'stock_code': stock_code}
        return corp_dict
    except Exception as e:
        return {}

# ==========================================
# 4. 데이터 수집 함수 (DART & KRX)
# ==========================================
def fetch_dart_financials(corp_code, bsns_year):
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"
    params = {'crtfc_key': DART_API_KEY, 'corp_code': corp_code, 'bsns_year': bsns_year, 'reprt_code': '11011'}
    data = {"유동자산": 0, "총부채": 0, "자기자본": 0, "당기순이익": 0}
    try:
        res = requests.get(url, params=params).json()
        if res.get('status') == '000':
            for item in res.get('list', []):
                account_nm = item.get('account_nm', '')
                amount = safe_float(item.get('thstrm_amount'))
                if '유동자산' in account_nm and '비유동자산' not in account_nm: data['유동자산'] = amount
                elif '부채총계' in account_nm or '총부채' in account_nm: data['총부채'] = amount
                elif '자본총계' in account_nm or '자기자본' in account_nm: data['자기자본'] = amount
                elif '당기순이익' in account_nm: data['당기순이익'] = amount
        return data
    except:
        return data

def fetch_dart_treasury_stock(corp_code, bsns_year):
    url = "https://opendart.fss.or.kr/api/stockTotqyEstb.json"
    params = {'crtfc_key': DART_API_KEY, 'corp_code': corp_code, 'bsns_year': bsns_year, 'reprt_code': '11011'}
    try:
        res = requests.get(url, params=params).json()
        if res.get('status') == '000':
            for item in res.get('list', []):
                if item.get('se') == '보통주': return safe_float(item.get('tesstk_co'))
        return 0
    except:
        return 0

@st.cache_data(ttl=3600)
def fetch_krx_market_data(target_date):
    """권한 이슈 없는 기본 KRX 시세 API 사용 (코스피 + 코스닥 병합)"""
    headers = {"AUTH_KEY": KRX_API_KEY}
    params = {"basDd": target_date}
    urls = [
        "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd", # 코스피
        "https://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd"  # 코스닥
    ]
    df_list = []
    for url in urls:
        try:
            res = requests.get(url, headers=headers, params=params).json()
            if 'OutBlock_1' in res and res['OutBlock_1']:
                df_list.append(pd.DataFrame(res['OutBlock_1']))
        except:
            pass
    if df_list:
        return pd.concat(df_list, ignore_index=True)
    return pd.DataFrame()

# ==========================================
# 5. 스트림릿 UI 구성 및 자체 계산 로직
# ==========================================
st.set_page_config(page_title="자동화 주식 가치 스크리너", layout="wide")
st.title("📊 자동화 주식 가치 스크리너 (자체 계산 엔진)")
st.markdown("엑셀에서 종목명 리스트를 복사하여 아래에 붙여넣으세요. 쉼표(,) 없이 줄바꿈만 되어 있어도 자동 인식합니다.")

corp_dict = load_dart_corp_codes()

st.sidebar.header("조회 설정")
target_year = st.sidebar.text_input("DART 사업연도 (YYYY)", value="2025")
krx_date = st.sidebar.text_input("KRX 기준일자 (YYYYMMDD)", value="20260504")
stock_input = st.text_area("종목명 입력 (여러 종목 복사-붙여넣기 가능)", height=150)

if st.button("데이터 조회 및 분석 실행"):
    if not stock_input.strip():
        st.warning("종목명을 입력해주세요.")
    else:
        with st.spinner("데이터 수집 및 투자 지표 자체 계산 중입니다..."):
            stock_names = [name.strip() for name in re.split(r'[\n\t,]+', stock_input) if name.strip()]
            
            # KRX 시세 데이터 한 번에 불러오기
            df_krx = fetch_krx_market_data(krx_date)
            
            results = []
            for name in stock_names:
                row = {
                    "종목명": name, "유동자산": 0, "총부채": 0, "BPS": 0, "업종PER": 0, 
                    "현재PER": 0, "PBR": 0, "EPS": 0, "당기순이익": 0, "자기자본": 0, "자사주": 0
                }
                
                corp_info = corp_dict.get(name)
                if corp_info:
                    corp_code = corp_info['corp_code']
                    stock_code = corp_info['stock_code']
                    
                    # 1. DART 데이터 수집
                    dart_fin = fetch_dart_financials(corp_code, target_year)
                    dart_ts = fetch_dart_treasury_stock(corp_code, target_year)
                    row.update(dart_fin)
                    row["자사주"] = dart_ts
                    
                    # 2. KRX 주가 매칭 및 밸류에이션 [직접 계산] (권한 이슈 우회)
                    if not df_krx.empty:
                        krx_row = df_krx[df_krx['ISU_CD'].str.endswith(stock_code[-6:])]
                        if not krx_row.empty:
                            close_price = safe_float(krx_row.iloc[0]['TDD_CLSPRC']) # 종가
                            listed_shares = safe_float(krx_row.iloc[0]['LIST_SHRS']) # 상장주식수
                            
                            net_income = row['당기순이익']
                            equity = row['자기자본']
                            
                            # 공식에 맞춰 파이썬이 스스로 지표 계산
                            if listed_shares > 0:
                                row['EPS'] = net_income / listed_shares
                                row['BPS'] = equity / listed_shares
                                
                                if row['EPS'] > 0: row['현재PER'] = close_price / row['EPS']
                                if row['BPS'] > 0: row['PBR'] = close_price / row['BPS']
                                
                                # ※ 업종PER은 특정 섹터 전체의 데이터 합산이 필요해 자체 계산이 불가하므로 0 유지
                
                results.append(row)
            
            df_result = pd.DataFrame(results)
            df_result = df_result[['종목명', '유동자산', '총부채', 'BPS', '업종PER', '현재PER', 'PBR', 'EPS', '당기순이익', '자기자본', '자사주']]
            
            st.success(f"총 {len(results)}개 종목 분석 및 자체 계산 완료!")
            
            st.dataframe(df_result.style.format({
                "유동자산": "{:,.0f}", "총부채": "{:,.0f}", "당기순이익": "{:,.0f}",
                "자기자본": "{:,.0f}", "자사주": "{:,.0f}", "BPS": "{:,.0f}", "EPS": "{:,.0f}",
                "업종PER": "{:.2f}", "현재PER": "{:.2f}", "PBR": "{:.2f}"
            }), use_container_width=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_result.to_excel(writer, index=False, sheet_name='Quant_Data')
            
            st.download_button(
                label="📥 엑셀(Excel) 파일로 다운로드",
                data=output.getvalue(),
                file_name=f"Quant_Data_{krx_date}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
