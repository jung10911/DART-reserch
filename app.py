import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import FinanceDataReader as fdr
import io
import re

# [1] 페이지 기본 설정
st.set_page_config(page_title="주식 재무정보 크롤러", layout="wide")

# [2] 종목명 -> 종목코드 변환 사전 생성 (캐싱하여 속도 향상)
@st.cache_data
def load_stock_codes():
    df_krx = fdr.StockListing('KRX')
    return dict(zip(df_krx['Name'], df_krx['Code']))

# [3] 네이버 금융 데이터 크롤링 함수
def get_financial_data(stock_name, code_dict):
    # 요청하신 순서대로 기본값 '0' 딕셔너리 세팅 (정보가 없을 시 0으로 표기)
    data = {
        '종목명': stock_name, '유동자산': '0', '총부채': '0', 'BPS': '0', 
        '업종PER': '0', '현재PER': '0', 'PBR': '0', 'EPS': '0', 
        '당기순이익': '0', '자기자본': '0', '자사주': '0'
    }
    
    code = code_dict.get(stock_name)
    if not code:
        return data # 상장되지 않았거나 이름이 틀린 경우 0 반환

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    try:
        # 네이버 금융 메인 페이지 요약 정보 크롤링
        main_url = f"https://finance.naver.com/item/main.naver?code={code}"
        res = requests.get(main_url, headers=headers)
        soup = BeautifulSoup(res.text, 'lxml')

        # 1. 투자지표 (현재PER, EPS, BPS, PBR) 추출
        try: data['현재PER'] = soup.select_one('#_per').text.strip()
        except: pass
        try: data['EPS'] = soup.select_one('#_eps').text.strip()
        except: pass
        try: data['BPS'] = soup.select_one('#_bps').text.strip()
        except: pass
        try: data['PBR'] = soup.select_one('#_pbr').text.strip()
        except: pass

        # 2. 업종PER 추출
        try:
            sector_table = soup.find('table', summary='동일업종 PER 정보')
            if sector_table:
                data['업종PER'] = sector_table.find('em').text.strip()
        except: pass

        # 3. 재무제표 (당기순이익, 자본 등) - Pandas read_html 활용
        try:
            dfs = pd.read_html(res.text, encoding='euc-kr')
            for df in dfs:
                # '주요재무정보' 테이블 찾기
                if '주요재무정보' in str(df.columns):
                    df.columns = df.columns.droplevel([0, 2]) # 복잡한 다중 인덱스 제거
                    df.set_index(df.columns[0], inplace=True)
                    recent_col = df.columns[-1] # 가장 최근 결산 데이터

                    if '당기순이익' in df.index:
                        val = str(df.loc['당기순이익', recent_col])
                        data['당기순이익'] = val if val != 'nan' else '0'
                    if '자본총계' in df.index: # 자본총계를 자기자본으로 대용
                        val = str(df.loc['자본총계', recent_col])
                        data['자기자본'] = val if val != 'nan' else '0'
                    if '부채총계' in df.index:
                        val = str(df.loc['부채총계', recent_col])
                        data['총부채'] = val if val != 'nan' else '0'
                    break
        except: pass

        # 참고: 유동자산과 자사주는 네이버 금융 메인 페이지 요약표에 항상 노출되지 않으므로,
        # 크롤링에 실패할 확률이 높습니다. 이 경우 조건에 따라 '0'으로 안전하게 처리됩니다.

    except Exception:
        pass # 통신 오류 발생 시에도 프로그램이 멈추지 않고 0으로 반환

    return data

# [4] Streamlit 웹 화면 구성
st.title("📊 주식 재무정보 일괄 크롤러")
st.markdown("**엑셀에서 복사한 여러 기업의 이름을 쉼표 없이 그대로 붙여넣기 하세요. (엔터 또는 띄어쓰기로 구분됩니다.)**")

# 종목코드 맵핑 로드
code_dict = load_stock_codes()

# 텍스트 입력 창 (엔터나 띄어쓰기로 자동 구분 처리)
user_input = st.text_area("기업명 입력창", height=150, placeholder="삼성전자\nSK하이닉스\n카카오")

if st.button("데이터 크롤링 시작"):
    if user_input:
        with st.spinner("네이버 금융에서 데이터를 수집 중입니다... 잠시만 기다려주세요."):
            # 정규식을 이용해 줄바꿈(\n)이나 공백(\s)을 기준으로 텍스트 분리 및 빈 문자열 제거
            corp_list = re.split(r'[\n\s]+', user_input.strip())
            corp_list = [c for c in corp_list if c]
            
            # 크롤링 실행
            results = []
            for corp in corp_list:
                results.append(get_financial_data(corp, code_dict))
                
            # 데이터프레임 변환 및 컬럼 순서 고정 (요청하신 순서)
            df = pd.DataFrame(results)
            columns_order = ['종목명', '유동자산', '총부채', 'BPS', '업종PER', '현재PER', 'PBR', 'EPS', '당기순이익', '자기자본', '자사주']
            df = df[columns_order]
            
            # 결과 화면 출력
            st.success("데이터 크롤링이 완료되었습니다!")
            st.dataframe(df)
            
            # 엑셀 다운로드 기능 변환 로직
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='재무정보')
            
            st.download_button(
                label="📥 엑셀 파일로 다운로드",
                data=excel_buffer.getvalue(),
                file_name="재무정보_크롤링결과.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    else:
        st.warning("기업명을 최소 한 개 이상 입력해 주세요.")
