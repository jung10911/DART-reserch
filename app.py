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

# [3] 고도화된 크롤링 함수 (네이버 메인 + FnGuide 재무상태표 연계)
def get_financial_data(stock_name, code_dict):
    data = {
        '종목명': stock_name, '유동자산': '0', '총부채': '0', 'BPS': '0', 
        '업종PER': '0', '현재PER': '0', 'PBR': '0', 'EPS': '0', 
        '당기순이익': '0', '자기자본': '0', '자사주': '0'
    }
    
    code = code_dict.get(stock_name)
    if not code:
        return data 

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    try:
        # --- [STEP 1] 네이버 금융 메인 페이지 (투자지표 및 기본 재무) ---
        main_url = f"https://finance.naver.com/item/main.naver?code={code}"
        res_main = requests.get(main_url, headers=headers)
        soup = BeautifulSoup(res_main.text, 'lxml')

        try: data['현재PER'] = soup.select_one('#_per').text.strip()
        except: pass
        try: data['EPS'] = soup.select_one('#_eps').text.strip()
        except: pass
        try: data['BPS'] = soup.select_one('#_bps').text.strip()
        except: pass
        try: data['PBR'] = soup.select_one('#_pbr').text.strip()
        except: pass

        try:
            sector_table = soup.find('table', summary='동일업종 PER 정보')
            if sector_table:
                data['업종PER'] = sector_table.find('em').text.strip()
        except: pass

        # 다중 인덱스(MultiIndex) 표 안전 파싱 (당기순이익, 총부채, 자기자본)
        try:
            dfs = pd.read_html(res_main.text, encoding='euc-kr')
            for df in dfs:
                if '주요재무정보' in str(df.columns):
                    # 다중 컬럼 레벨을 하나의 문자열로 합쳐서 구조 단순화
                    df.columns = ['_'.join(str(c) for c in col).strip() for col in df.columns]
                    df.set_index(df.columns[0], inplace=True) 
                    
                    # '최근 연간 실적' 중 가장 마지막(최근) 결산 데이터 열 찾기
                    annual_cols = [c for c in df.columns if '최근 연간 실적' in c]
                    recent_col = annual_cols[-1] if annual_cols else df.columns[-1]

                    # 인덱스 부분 매칭으로 값 추출 함수
                    def get_main_val(keyword):
                        for idx in df.index:
                            if pd.isna(idx): continue
                            if keyword in str(idx):
                                val = df.loc[idx, recent_col]
                                if isinstance(val, pd.Series): val = val.iloc[0]
                                return str(val) if pd.notna(val) else '0'
                        return '0'

                    data['당기순이익'] = get_main_val('당기순이익')
                    data['총부채'] = get_main_val('부채총계')
                    data['자기자본'] = get_main_val('자본총계')
                    break
        except: pass

        # --- [STEP 2] FnGuide 상세 재무상태표 (메인에 없는 유동자산, 자사주 추출) ---
        try:
            fn_url = f"https://comp.fnguide.com/SVO2/ASP/SVD_Finance.asp?pGB=1&gicode=A{code}"
            res_fn = requests.get(fn_url, headers=headers)
            dfs_fn = pd.read_html(res_fn.text)
            
            for df_fn in dfs_fn:
                # 재무상태표 테이블 찾기
                if any('유동자산' in str(x) for x in df_fn.iloc[:, 0].values):
                    df_fn.set_index(df_fn.columns[0], inplace=True)
                    recent_col_fn = df_fn.columns[-1] 
                    
                    def get_fn_val(keyword):
                        for idx in df_fn.index:
                            if pd.isna(idx): continue
                            if keyword in str(idx):
                                val = df_fn.loc[idx, recent_col_fn]
                                if isinstance(val, pd.Series): val = val.iloc[0]
                                return str(val) if pd.notna(val) else '0'
                        return '0'

                    data['유동자산'] = get_fn_val('유동자산')
                    data['자사주'] = get_fn_val('자기주식') # 회계상 자사주는 '자기주식'으로 표기됨
                    break
        except: pass

    except Exception:
        pass 

    return data

# [4] Streamlit 웹 화면 구성
st.title("📊 주식 재무정보 일괄 크롤러 (심층 데이터 포함)")
st.markdown("**엑셀에서 복사한 여러 기업의 이름을 쉼표 없이 그대로 붙여넣기 하세요.**")

code_dict = load_stock_codes()

user_input = st.text_area("기업명 입력창", height=150, placeholder="삼성전자\nSK하이닉스\n미래컴퍼니")

if st.button("데이터 크롤링 시작"):
    if user_input:
        with st.spinner("네이버 금융 및 재무제표 원본 데이터를 분석 중입니다..."):
            corp_list = re.split(r'[\n\s]+', user_input.strip())
            corp_list = [c for c in corp_list if c]
            
            results = []
            for corp in corp_list:
                results.append(get_financial_data(corp, code_dict))
                
            # 지정된 컬럼 순서 고정
            df = pd.DataFrame(results)
            columns_order = ['종목명', '유동자산', '총부채', 'BPS', '업종PER', '현재PER', 'PBR', 'EPS', '당기순이익', '자기자본', '자사주']
            df = df[columns_order]
            
            st.success("심층 재무 데이터 크롤링이 완료되었습니다!")
            st.dataframe(df)
            
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='재무정보')
            
            st.download_button(
                label="📥 엑셀 파일로 다운로드",
                data=excel_buffer.getvalue(),
                file_name="재무정보_심층크롤링.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    else:
        st.warning("기업명을 입력해 주세요.")
