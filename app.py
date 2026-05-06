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
    """문자열 숫자를 안전하게 실수로 변환하며, 에러 시 0을 반환합니다."""
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
# 3. DART 고유번호 맵핑 (종목명 -> DART 고유번호)
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
        st.error("DART 고유번호 목록을 불러오지 못했습니다.")
        return {}

# ==========================================
# 4. 데이터 수집 함수 (DART & KRX)
# ==========================================
def fetch_dart_financials(corp_code, bsns_year):
    """DART 재무제표 API (유연한 텍스트 매칭 적용)"""
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"
    params = {
        'crtfc_key': DART_API_KEY,
        'corp_code': corp_code,
        'bsns_year': bsns_year,
        'reprt_code': '11011' # 사업보고서
    }
    
    data = {"유동자산": 0, "총부채": 0, "자기자본": 0, "당기순이익": 0}
    try:
        res = requests.get(url, params=params).json()
        if res.get('status') == '000':
            for item in res.get('list', []):
                # CFS(연결재무제표) 또는 OFS(개별재무제표) 중 우선순위 적용 가능하나 여기선 모두 스캔
                account_nm = item.get('account_nm', '')
                amount = safe_float(item.get('thstrm_amount'))
                
                # [핵심 수정] 텍스트가 '포함'되어 있는지로 검색 필터 강화
                if '유동자산' in account_nm and '비유동자산' not in account_nm: 
                    data['유동자산'] = amount
                elif '부채총계' in account_nm or '총부채' in account_nm: 
                    data['총부채'] = amount
                elif '자본총계' in account_nm or '자기자본' in account_nm: 
                    data['자기자본'] = amount
                elif '당기순이익' in account_nm: # 당기순이익(손실), 연결당기순이익 모두 커버
                    data['당기순이익'] = amount
        return data
    except:
        return data

def fetch_dart_treasury_stock(corp_code, bsns_year):
    """DART 주식총수 API (자사주)"""
    url = "https://opendart.fss.or.kr/api/stockTotqyEstb.json"
    params = {
        'crtfc_key': DART_API_KEY,
        'corp_code': corp_code,
        'bsns_year': bsns_year,
        'reprt_code': '11011'
    }
    try:
        res = requests.get(url, params=params).json()
        if res.get('status') == '000':
            for item in res.get('list', []):
                if item.get('se') == '보통주':
                    return safe_float(item.get('tesstk_co'))
        return 0
    except:
        return 0

def fetch_krx_valuation(stock_code, target_date):
    """
    KRX 투자지표 전용 API
    ※ 주의: KRX OPEN API 포털에서 '투자분석 - 개별종목 투자지표' 사용 권한이 있어야 합니다.
    """
    # [핵심 수정] 일별 매매정보(stk_bydd_trd)가 아닌, 투자지표(stk_val_bydd 또는 관련 엔드포인트) 호출
    url = "https://data-dbg.krx.co.kr/svc/apis/sto/stk_val_bydd" 
    headers = {"AUTH_KEY": KRX_API_KEY}
    params = {"basDd": target_date}
    
    data = {"BPS": 0, "업종PER": 0, "현재PER": 0, "PBR": 0, "EPS": 0}
    try:
        res = requests.get(url, headers=headers, params=params).json()
        outblock = res.get('OutBlock_1', [])
        
        for item in outblock:
            if item.get('ISU_CD', '')[-6:] == stock_code[-6:]:
                data['현재PER'] = safe_float(item.get('PER', 0))
                data['PBR'] = safe_float(item.get('PBR', 0))
                data['EPS'] = safe_float(item.get('EPS', 0))
                data['BPS'] = safe_float(item.get('BPS', 0))
                # 업종 PER은 제공 여부에 따라 키값이 다를 수 있으나 보편적인 IDX_PER로 세팅
                data['업종PER'] = safe_float(item.get('IDX_PER', item.get('IND_PER', 0))) 
                break
        return data
    except:
        return data

# ==========================================
# 5. 스트림릿 UI 구성
# ==========================================
st.set_page_config(page_title="자동화 주식 가치 스크리너", layout="wide")

st.title("📊 자동화 주식 가치 스크리너 (DART + KRX)")
st.markdown("엑셀에서 종목명 리스트를 복사하여 아래에 붙여넣으세요. 쉼표(,) 없이 줄바꿈만 되어 있어도 자동 인식합니다.")

corp_dict = load_dart_corp_codes()

st.sidebar.header("조회 설정")
target_year = st.sidebar.text_input("DART 사업연도 (YYYY)", value="2025") # 조회 원하는 년도 입력
krx_date = st.sidebar.text_input("KRX 기준일자 (YYYYMMDD)", value="20260504")

stock_input = st.text_area("종목명 입력 (여러 종목 복사-붙여넣기 가능)", height=150)

if st.button("데이터 조회 및 분석 실행"):
    if not stock_input.strip():
        st.warning("조회할 종목명을 입력해주세요.")
    else:
        with st.spinner("API 데이터를 수집 중입니다..."):
            stock_names = [name.strip() for name in re.split(r'[\n\t,]+', stock_input) if name.strip()]
            results = []
            
            for name in stock_names:
                row = {
                    "종목명": name,
                    "유동자산": 0, "총부채": 0, "BPS": 0, "업종PER": 0, 
                    "현재PER": 0, "PBR": 0, "EPS": 0, "당기순이익": 0, 
                    "자기자본": 0, "자사주": 0
                }
                
                corp_info = corp_dict.get(name)
                if corp_info:
                    corp_code = corp_info['corp_code']
                    stock_code = corp_info['stock_code']
                    
                    dart_fin = fetch_dart_financials(corp_code, target_year)
                    dart_ts = fetch_dart_treasury_stock(corp_code, target_year)
                    krx_val = fetch_krx_valuation(stock_code, krx_date)
                    
                    row.update(dart_fin)
                    row["자사주"] = dart_ts
                    row.update(krx_val)
                
                results.append(row)
            
            df_result = pd.DataFrame(results)
            # 출력 순서 강제 고정
            df_result = df_result[['종목명', '유동자산', '총부채', 'BPS', '업종PER', '현재PER', 'PBR', 'EPS', '당기순이익', '자기자본', '자사주']]
            
            st.success(f"총 {len(results)}개 종목 분석 완료!")
            
            # 소수점 2자리(PER, PBR 등)와 천 단위 콤마(자산 등) 포맷팅
            st.dataframe(df_result.style.format({
                "유동자산": "{:,.0f}", "총부채": "{:,.0f}", "당기순이익": "{:,.0f}",
                "자기자본": "{:,.0f}", "자사주": "{:,.0f}", "BPS": "{:,.0f}", "EPS": "{:,.0f}",
                "업종PER": "{:.2f}", "현재PER": "{:.2f}", "PBR": "{:.2f}"
            }), use_container_width=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_result.to_excel(writer, index=False, sheet_name='Quant_Data')
            processed_data = output.getvalue()
            
            st.download_button(
                label="📥 엑셀(Excel) 파일로 다운로드",
                data=processed_data,
                file_name=f"Quant_Data_{krx_date}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
