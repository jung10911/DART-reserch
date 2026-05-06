import streamlit as st
import pandas as pd
import requests
import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
import re
from bs4 import BeautifulSoup # 크롤링 라이브러리 추가

# ==========================================
# 1. API KEY 세팅
# ==========================================
DART_API_KEY = "0d3337714983152206d438906ff525000677118e"

# ==========================================
# 2. 공통 유틸리티 함수
# ==========================================
def safe_float(val):
    if pd.isna(val) or val is None:
        return 0.0
    val_str = str(val).replace(',', '').replace('배', '').replace('원', '').strip()
    if val_str in ['-', '', 'NaN', 'null', 'N/A']:
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
    except:
        return {}

# ==========================================
# 4. 데이터 수집 함수 (DART API)
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

# ==========================================
# 5. 핵심: 네이버 금융 웹 크롤링 함수
# ==========================================
def fetch_naver_finance(stock_code):
    """네이버 금융 페이지에서 투자 지표 크롤링"""
    # 네이버 웹 크롤링 차단 방지를 위한 User-Agent 헤더 추가
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    url = f"https://finance.naver.com/item/main.naver?code={stock_code}"
    
    data = {"BPS": 0, "업종PER": 0, "현재PER": 0, "PBR": 0, "EPS": 0}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. PER, EPS 추출
        per_em = soup.select_one('#_per')
        eps_em = soup.select_one('#_eps')
        if per_em: data['현재PER'] = safe_float(per_em.text)
        if eps_em: data['EPS'] = safe_float(eps_em.text)
        
        # 2. PBR, BPS 추출 (클래스와 태그 구조 기반 탐색)
        pbr_em = soup.select_one('#_pbr')
        bps_td = soup.select_one('em#_bps') # BPS 태그 처리
        if pbr_em: data['PBR'] = safe_float(pbr_em.text)
        
        # BPS는 태그가 명확하지 않을 때를 대비해 표 데이터에서 직접 긁어오기
        table_bps = soup.find('th', string=re.compile('BPS'))
        if table_bps:
            bps_val = table_bps.find_next_sibling('td').find('em')
            if bps_val: data['BPS'] = safe_float(bps_val.text)
            
        # 3. 업종 PER 추출
        upjong_per_em = soup.select_one('table.summary_info div.gray th:-soup-contains("업종PER") + td em')
        if not upjong_per_em: # 다른 구조일 경우 대비
             upjong_per = soup.find('th', string=re.compile('업종PER'))
             if upjong_per:
                 upjong_per_em = upjong_per.find_next_sibling('td').find('em')
                 
        if upjong_per_em:
            data['업종PER'] = safe_float(upjong_per_em.text)

        return data
    except Exception as e:
        print(f"[{stock_code}] 크롤링 에러: {e}")
        return data

# ==========================================
# 6. 스트림릿 UI 구성 및 최종 병합
# ==========================================
st.set_page_config(page_title="자동화 퀀트 스크리너", layout="wide")
st.title("📊 자동화 퀀트 스크리너 (DART + 네이버금융)")
st.markdown("엑셀에서 종목명 리스트를 복사하여 아래에 붙여넣으세요. 쉼표 없이 줄바꿈만 되어 있어도 자동 인식합니다.")

corp_dict = load_dart_corp_codes()

st.sidebar.header("조회 설정")
target_year = st.sidebar.text_input("DART 사업연도 (YYYY)", value="2025")
stock_input = st.text_area("종목명 입력 (여러 종목 복사-붙여넣기 가능)", height=150)

if st.button("데이터 조회 및 분석 실행"):
    if not stock_input.strip():
        st.warning("종목명을 입력해주세요.")
    else:
        with st.spinner("DART API 수집 및 네이버 금융 크롤링 중입니다... (종목이 많으면 수 분 소요)"):
            stock_names = [name.strip() for name in re.split(r'[\n\t,]+', stock_input) if name.strip()]
            results = []
            
            # 크롤링 진행률 표시 바
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for idx, name in enumerate(stock_names):
                status_text.text(f"분석 중: {name} ({idx+1}/{len(stock_names)})")
                row = {
                    "종목명": name, "유동자산": 0, "총부채": 0, "BPS": 0, "업종PER": 0, 
                    "현재PER": 0, "PBR": 0, "EPS": 0, "당기순이익": 0, "자기자본": 0, "자사주": 0
                }
                
                corp_info = corp_dict.get(name)
                if corp_info:
                    corp_code = corp_info['corp_code']
                    stock_code = corp_info['stock_code']
                    
                    # 1. DART API 호출
                    dart_fin = fetch_dart_financials(corp_code, target_year)
                    dart_ts = fetch_dart_treasury_stock(corp_code, target_year)
                    row.update(dart_fin)
                    row["자사주"] = dart_ts
                    
                    # 2. 네이버 금융 크롤링 호출
                    naver_data = fetch_naver_finance(stock_code)
                    row.update(naver_data)
                
                results.append(row)
                progress_bar.progress((idx + 1) / len(stock_names))
            
            status_text.empty()
            
            # 데이터 정렬 및 출력
            df_result = pd.DataFrame(results)
            df_result = df_result[['종목명', '유동자산', '총부채', 'BPS', '업종PER', '현재PER', 'PBR', 'EPS', '당기순이익', '자기자본', '자사주']]
            
            st.success(f"총 {len(results)}개 종목 분석 완료!")
            
            st.dataframe(df_result.style.format({
                "유동자산": "{:,.0f}", "총부채": "{:,.0f}", "당기순이익": "{:,.0f}",
                "자기자본": "{:,.0f}", "자사주": "{:,.0f}", "BPS": "{:,.0f}", "EPS": "{:,.0f}",
                "업종PER": "{:.2f}", "현재PER": "{:.2f}", "PBR": "{:.2f}"
            }), use_container_width=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_result.to_excel(writer, index=False, sheet_name='Quant_Data')
            
            today_str = datetime.today().strftime('%Y%m%d')
            st.download_button(
                label="📥 엑셀(Excel) 파일로 다운로드",
                data=output.getvalue(),
                file_name=f"Quant_Naver_Data_{today_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
