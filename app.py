import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import FinanceDataReader as fdr
import io
import re

# [1] 페이지 기본 설정
st.set_page_config(page_title="주식 재무정보 크롤러", layout="wide")

# [2] 종목명 -> 종목코드 변환 사전
@st.cache_data
def load_stock_codes():
    df_krx = fdr.StockListing('KRX')
    return dict(zip(df_krx['Name'], df_krx['Code']))

# [3] 강력한 직접 태그 추출 방식 (표 구조 붕괴 무시)
def get_financial_data(stock_name, code_dict):
    data = {
        '종목명': stock_name, '유동자산': '0', '총부채': '0', 'BPS': '0', 
        '업종PER': '0', '현재PER': '0', 'PBR': '0', 'EPS': '0', 
        '당기순이익': '0', '자기자본': '0', '자사주': '0'
    }
    
    code = code_dict.get(stock_name)
    if not code:
        return data 

    # 봇 차단 방지를 위한 강력한 User-Agent
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        # --- [STEP 1] 네이버 금융 메인 페이지 ---
        main_url = f"https://finance.naver.com/item/main.naver?code={code}"
        res_main = requests.get(main_url, headers=headers)
        soup = BeautifulSoup(res_main.text, 'html.parser')

        # 1. 투자지표 (현재PER, EPS, BPS, PBR)
        try: data['현재PER'] = soup.select_one('#_per').text.strip().replace(',', '')
        except: pass
        try: data['EPS'] = soup.select_one('#_eps').text.strip().replace(',', '')
        except: pass
        try: data['PBR'] = soup.select_one('#_pbr').text.strip().replace(',', '')
        except: pass
        try: data['BPS'] = soup.select_one('#_bps').text.strip().replace(',', '')
        except: pass

        # 2. 업종PER
        try:
            sector_table = soup.find('table', summary='동일업종 PER 정보')
            if sector_table:
                data['업종PER'] = sector_table.find('em').text.strip()
        except: pass

        # 3. 재무제표 (당기순이익, 총부채, 자기자본, BPS 2차 추출)
        # pandas read_html 대신 HTML <tr> <th> <td> 직접 추적 (가장 확실한 방법)
        try:
            tbody = soup.select_one('table.tb_type1_ifrs > tbody')
            if tbody:
                for tr in tbody.find_all('tr'):
                    th = tr.find('th')
                    if not th: continue
                    th_text = th.text.strip()
                    
                    # 최근 4개년 연간 데이터 중 가장 최근(오른쪽) 값 추출
                    tds = [td.text.strip().replace(',', '') for td in tr.find_all('td')]
                    annuals = [x for x in tds[:4] if x and x != '-' and x != '']
                    recent_val = annuals[-1] if annuals else '0'

                    if th_text == '당기순이익':
                        data['당기순이익'] = recent_val
                    elif th_text == '부채총계':
                        data['총부채'] = recent_val
                    elif th_text == '자본총계':
                        data['자기자본'] = recent_val
                    elif 'BPS' in th_text and data['BPS'] == '0':
                        data['BPS'] = recent_val
        except: pass

        # --- [STEP 2] FnGuide 상세 재무상태표 ---
        # 유동자산, 자사주 추출
        fn_url = f"https://comp.fnguide.com/SVO2/ASP/SVD_Finance.asp?pGB=1&gicode=A{code}"
        res_fn = requests.get(fn_url, headers=headers)
        soup_fn = BeautifulSoup(res_fn.text, 'html.parser')
        
        try:
            daecha = soup_fn.find('div', id='div_daechaY')
            if daecha:
                for tr in daecha.find_all('tr'):
                    th = tr.find('th')
                    if not th: continue
                    
                    # '유동자산계', '유동자산(*)' 등 웹페이지의 불순물을 제거하고 순수 한글만 추출
                    clean_th = re.sub(r'[^가-힣]', '', th.text)
                    
                    tds = [td.text.strip().replace(',', '') for td in tr.find_all('td')]
                    valid_vals = [x for x in tds if x and x != '-' and x != '0' and x != '']
                    recent_val_fn = valid_vals[-1] if valid_vals else '0'

                    if '유동자산' in clean_th:
                        data['유동자산'] = recent_val_fn
                    elif '자기주식' in clean_th:
                        data['자사주'] = recent_val_fn
        except: pass

    except Exception:
        pass 

    return data

# [4] Streamlit 웹 화면 구성
st.title("📊 주식 재무정보 일괄 크롤러 (태그 직접 추적형)")
st.markdown("**엑셀에서 복사한 여러 기업의 이름을 쉼표 없이 그대로 붙여넣기 하세요.**")

code_dict = load_stock_codes()

user_input = st.text_area("기업명 입력창", height=150, placeholder="삼성전자\nSK하이닉스")

if st.button("데이터 크롤링 시작"):
    if user_input:
        with st.spinner("웹페이지 표 구조에 얽매이지 않고 정확한 숫자를 강제 추출 중입니다..."):
            corp_list = re.split(r'[\n\s]+', user_input.strip())
            corp_list = [c for c in corp_list if c]
            
            results = []
            for corp in corp_list:
                results.append(get_financial_data(corp, code_dict))
                
            df = pd.DataFrame(results)
            columns_order = ['종목명', '유동자산', '총부채', 'BPS', '업종PER', '현재PER', 'PBR', 'EPS', '당기순이익', '자기자본', '자사주']
            df = df[columns_order]
            
            st.success("모든 데이터 추출이 완료되었습니다!")
            st.dataframe(df)
            
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='재무정보')
            
            st.download_button(
                label="📥 엑셀 파일로 다운로드",
                data=excel_buffer.getvalue(),
                file_name="재무정보_최종완성본.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    else:
        st.warning("기업명을 입력해 주세요.")
