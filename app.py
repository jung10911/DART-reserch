import streamlit as st
import pandas as pd
import requests
import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime

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
@st.cache_data(ttl=86400) # 하루 한 번만 다운로드 및 캐싱
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
    """DART 재무제표 API (유동자산, 총부채, 자본, 당기순이익)"""
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"
    params = {
        'crtfc_key': DART_API_KEY,
        'corp_code': corp_code,
        'bsns_year': bsns_year,
        'reprt_code': '11011' # 11011: 사업보고서
    }
    
    # 기본값 0 세팅
    data = {"유동자산": 0, "총부채": 0, "자기자본": 0, "당기순이익": 0}
    try:
        res = requests.get(url, params=params).json()
        if res.get('status') == '000':
            for item in res.get('list', []):
                # 재무제표 구분 기준 (연결재무제표 우선)
                if item.get('fs_div') == 'CFS': 
                    account_nm = item.get('account_nm')
                    amount = safe_float(item.get('thstrm_amount')) # 당기 금액
                    
                    if account_nm == '유동자산': data['유동자산'] = amount
                    elif account_nm == '부채총계': data['총부채'] = amount
                    elif account_nm == '자본총계': data['자기자본'] = amount
                    elif account_nm == '당기순이익': data['당기순이익'] = amount
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
                    return safe_float(item.get('tesstk_co')) # 자기주식수
        return 0
    except:
        return 0

def fetch_krx_valuation(stock_code, target_date):
    """
    KRX 개별종목 지표 수집
    ※ 주가 데이터 API를 활용하며, 응답값에 PER, PBR 등이 없을 시 0으로 안전 처리됨.
    """
    url = "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd" # 코스피 예시 (코스닥 통합 검색 로직 생략하고 안전하게 get)
    headers = {"AUTH_KEY": KRX_API_KEY}
    params = {"basDd": target_date}
    
    data = {"BPS": 0, "업종PER": 0, "현재PER": 0, "PBR": 0, "EPS": 0}
    try:
        res = requests.get(url, headers=headers, params=params).json()
        outblock = res.get('OutBlock_1', [])
        
        # 입력한 종목코드와 일치하는 데이터 찾기
        for item in outblock:
            if item.get('ISU_CD', '')[-6:] == stock_code[-6:]: # 코드 6자리 비교
                data['현재PER'] = safe_float(item.get('PER', 0))
                data['업종PER'] = safe_float(item.get('IDX_PER', 0)) # API 스펙에 따라 다를 수 있음
                data['PBR'] = safe_float(item.get('PBR', 0))
                data['EPS'] = safe_float(item.get('EPS', 0))
                data['BPS'] = safe_float(item.get('BPS', 0))
                break
        return data
    except:
        return data

# ==========================================
# 5. 스트림릿 UI 구성
# ==========================================
st.set_page_config(page_title="자동화 주식 가치 스크리너", layout="wide")

st.title("📊 자동화 주식 가치 스크리너 (DART + KRX)")
st.markdown("엑셀에서 종목명 리스트를 복사하여 아래에 붙여넣으세요. 쉼표(,) 없이 엔터나 띄어쓰기만 되어 있어도 자동 인식합니다.")

# DART 고유번호 딕셔너리 로드
corp_dict = load_dart_corp_codes()

# 사이드바 설정
st.sidebar.header("조회 설정")
target_year = st.sidebar.text_input("DART 사업연도 (YYYY)", value="2023")
krx_date = st.sidebar.text_input("KRX 기준일자 (YYYYMMDD)", value=datetime.today().strftime('%Y%m%d'))

# 종목명 입력창
stock_input = st.text_area("종목명 입력 (여러 종목 복사-붙여넣기 가능)", height=150, placeholder="삼성전자\nSK하이닉스\n현대차")

if st.button("데이터 조회 및 분석 실행"):
    if not stock_input.strip():
        st.warning("조회할 종목명을 입력해주세요.")
    else:
        with st.spinner("API 데이터를 수집 중입니다. 종목이 많을수록 시간이 소요될 수 있습니다..."):
            
            # 1. 입력된 텍스트 파싱 (줄바꿈, 탭, 공백 기준으로 분리)
            import re
            stock_names = [name.strip() for name in re.split(r'[\n\t,]+', stock_input) if name.strip()]
            
            results = []
            
            # 2. 각 종목별 데이터 수집 루프
            for name in stock_names:
                row = {
                    "종목명": name,
                    "유동자산": 0, "총부채": 0, "BPS": 0, "업종PER": 0, 
                    "현재PER": 0, "PBR": 0, "EPS": 0, "당기순이익": 0, 
                    "자기자본": 0, "자사주": 0
                }
                
                # DART 고유번호 및 종목코드 찾기
                corp_info = corp_dict.get(name)
                
                if corp_info:
                    corp_code = corp_info['corp_code']
                    stock_code = corp_info['stock_code']
                    
                    # API 호출
                    dart_fin = fetch_dart_financials(corp_code, target_year)
                    dart_ts = fetch_dart_treasury_stock(corp_code, target_year)
                    krx_val = fetch_krx_valuation(stock_code, krx_date)
                    
                    # 데이터 맵핑
                    row["유동자산"] = dart_fin["유동자산"]
                    row["총부채"] = dart_fin["총부채"]
                    row["자기자본"] = dart_fin["자기자본"]
                    row["당기순이익"] = dart_fin["당기순이익"]
                    row["자사주"] = dart_ts
                    
                    row["BPS"] = krx_val["BPS"]
                    row["업종PER"] = krx_val["업종PER"]
                    row["현재PER"] = krx_val["현재PER"]
                    row["PBR"] = krx_val["PBR"]
                    row["EPS"] = krx_val["EPS"]
                
                results.append(row)
            
            # 3. 데이터프레임 생성 및 출력
            df_result = pd.DataFrame(results)
            st.success(f"총 {len(results)}개 종목 분석 완료!")
            
            # 화면 출력 (천 단위 콤마 포맷팅)
            st.dataframe(df_result.style.format({
                "유동자산": "{:,.0f}", "총부채": "{:,.0f}", "당기순이익": "{:,.0f}",
                "자기자본": "{:,.0f}", "자사주": "{:,.0f}", "BPS": "{:,.0f}", "EPS": "{:,.0f}"
            }), use_container_width=True)
            
            # 4. 엑셀 다운로드 기능
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
