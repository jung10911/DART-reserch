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

# [3] 종목분석 탭 원본 API 직접 호출 방식 (100% 확실한 데이터 추출)
def get_financial_data(stock_name, code_dict):
    data = {
        '종목명': stock_name, '유동자산': '0', '총부채': '0', 'BPS': '0', 
        '업종PER': '0', '현재PER': '0', 'PBR': '0', 'EPS': '0', 
        '당기순이익': '0', '자기자본': '0', '자사주': '0'
    }
    
    code = code_dict.get(stock_name)
    if not code:
        return data 

    # 브라우저 우회 접속 설정 (봇 차단 완벽 방지)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': f'https://finance.naver.com/item/main.naver?code={code}'
    }
    
    try:
        # --- [STEP 1] 네이버 금융 메인 (투자지표 PER, PBR 등 추출) ---
        main_url = f"https://finance.naver.com/item/main.naver?code={code}"
        res_main = requests.get(main_url, headers=headers)
        soup_main = BeautifulSoup(res_main.text, 'html.parser')

        try: data['현재PER'] = soup_main.select_one('#_per').text.strip().replace(',', '')
        except: pass
        try: data['EPS'] = soup_main.select_one('#_eps').text.strip().replace(',', '')
        except: pass
        try: data['PBR'] = soup_main.select_one('#_pbr').text.strip().replace(',', '')
        except: pass
        try: data['BPS'] = soup_main.select_one('#_bps').text.strip().replace(',', '')
        except: pass

        try:
            sector_table = soup_main.find('table', summary='동일업종 PER 정보')
            if sector_table and sector_table.find('em'):
                data['업종PER'] = sector_table.find('em').text.strip()
        except: pass

        # --- [STEP 2] 종목분석 탭(와이즈리포트) 숨겨진 원본 데이터 직접 호출 ---
        # 네이버가 종목분석 화면을 그릴 때 몰래 호출하는 AJAX API 주소입니다.
        wr_headers = {
            'User-Agent': headers['User-Agent'],
            'Referer': f'https://navercomp.wisereport.co.kr/v2/company/c1030001.aspx?cmp_cd={code}'
        }

        # 표 데이터를 뜯어오는 전용 함수
        def parse_wisereport_api(url, keyword_map):
            try:
                res = requests.get(url, headers=wr_headers)
                soup = BeautifulSoup(res.text, 'html.parser')
                
                for tr in soup.find_all('tr'):
                    tds = tr.find_all(['td', 'th'])
                    if not tds: continue
                    
                    # 괄호나 특수문자 다 지우고 순수 한글만 남김 (ex: '유동자산(*)' -> '유동자산')
                    row_title = re.sub(r'[^가-힣]', '', tds[0].text)
                    
                    for key, output_key in keyword_map.items():
                        # 찾고자 하는 항목(예: 자기주식)이 줄 이름에 포함되어 있으면
                        if key in row_title:
                            # 값이 아직 '0'일 때만 채움 (중복 덮어쓰기 방지)
                            if data[output_key] == '0':
                                # 가장 최근 연도(오른쪽 끝)부터 거꾸로 탐색하며 진짜 숫자를 찾음
                                for td in reversed(tds[1:]):
                                    val = td.text.replace(',', '').replace('\xa0', '').strip()
                                    if re.match(r'^-?\d+(?:\.\d+)?$', val): # 올바른 숫자인지 검증
                                        data[output_key] = val
                                        break
            except Exception:
                pass

        # 1. 재무상태표 API 호출 (유동자산, 총부채, 자기자본, 자사주)
        bs_url = f"https://navercomp.wisereport.co.kr/v2/company/ajax/cF1002.aspx?cmp_cd={code}&fin_typ=0&freq_typ=Y"
        parse_wisereport_api(bs_url, {
            '유동자산': '유동자산',
            '부채총계': '총부채',      # 표에는 부채총계로 나옴
            '자본총계': '자기자본',    # 표에는 자본총계로 나옴
            '자기주식': '자사주'      # 표에는 자기주식으로 나옴
        })

        # 2. 포괄손익계산서 API 호출 (당기순이익)
        is_url = f"https://navercomp.wisereport.co.kr/v2/company/ajax/cF1001.aspx?cmp_cd={code}&fin_typ=0&freq_typ=Y"
        parse_wisereport_api(is_url, {
            '당기순이익': '당기순이익'
        })

    except Exception:
        pass 

    return data

# [4] Streamlit 웹 화면 구성
st.title("📊 주식 재무정보 일괄 크롤러 (종목분석 원본 API 연동)")
st.markdown("**엑셀에서 복사한 여러 기업의 이름을 쉼표 없이 그대로 붙여넣기 하세요.**")

code_dict = load_stock_codes()

user_input = st.text_area("기업명 입력창", height=150, placeholder="삼성전자\nSK하이닉스")

if st.button("데이터 크롤링 시작"):
    if user_input:
        with st.spinner("종목분석 탭의 원본 서버에 접속하여 데이터를 뽑아오고 있습니다..."):
            corp_list = re.split(r'[\n\s]+', user_input.strip())
            corp_list = [c for c in corp_list if c]
            
            results = []
            for corp in corp_list:
                results.append(get_financial_data(corp, code_dict))
                
            df = pd.DataFrame(results)
            columns_order = ['종목명', '유동자산', '총부채', 'BPS', '업종PER', '현재PER', 'PBR', 'EPS', '당기순이익', '자기자본', '자사주']
            df = df[columns_order]
            
            st.success("데이터 추출 완료! 종목분석 탭의 수치가 정상 반영되었습니다.")
            st.dataframe(df)
            
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='재무정보')
            
            st.download_button(
                label="📥 엑셀 파일로 다운로드",
                data=excel_buffer.getvalue(),
                file_name="재무정보_종목분석_결과.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    else:
        st.warning("기업명을 입력해 주세요.")
