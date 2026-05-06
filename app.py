import streamlit as st
import pandas as pd
import requests
import io
import re
from bs4 import BeautifulSoup
from datetime import datetime

# ==========================================
# 1. 공통 유틸리티 함수
# ==========================================
def safe_float(val):
    if pd.isna(val) or val is None:
        return 0.0
    val_str = str(val).replace(',', '').replace('배', '').replace('원', '').replace('%', '').strip()
    if val_str in ['-', '', 'NaN', 'null', 'N/A']:
        return 0.0
    try:
        return float(val_str)
    except ValueError:
        return 0.0

# ==========================================
# 2. 종목명 -> 종목코드 변환 (네이버)
# ==========================================
def get_stock_code_from_naver(stock_name):
    url = f"https://ac.finance.naver.com/ac?q={stock_name}&q_enc=utf-8&st=111&frm=stock&r_format=json&r_enc=utf-8&r_unicode=0&t_koreng=1&req=1"
    try:
        res = requests.get(url).json()
        items = res.get('items', [[]])[0]
        if items and len(items) > 0:
            return items[0][1][0]
    except:
        pass
    return None

# ==========================================
# 3. 크롤링 엔진: 네이버 + 에프앤가이드(재무상태표)
# ==========================================
def fetch_finance_data(stock_code):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    data = {
        "유동자산": 0, "총부채": 0, "BPS": 0, "업종PER": 0, 
        "현재PER": 0, "PBR": 0, "EPS": 0, "당기순이익": 0, 
        "자기자본": 0, "자사주": 0
    }
    
    # [STEP 1] 네이버 금융 메인 (PER, PBR, EPS 등)
    naver_url = f"https://finance.naver.com/item/main.naver?code={stock_code}"
    try:
        res_naver = requests.get(naver_url, headers=headers)
        soup_naver = BeautifulSoup(res_naver.text, 'html.parser')
        
        per_em = soup_naver.select_one('#_per')
        eps_em = soup_naver.select_one('#_eps')
        pbr_em = soup_naver.select_one('#_pbr')
        
        if per_em: data['현재PER'] = safe_float(per_em.text)
        if eps_em: data['EPS'] = safe_float(eps_em.text)
        if pbr_em: data['PBR'] = safe_float(pbr_em.text)
        
        upjong_per_em = soup_naver.select_one('table.summary_info th:-soup-contains("업종PER") + td em')
        if upjong_per_em: data['업종PER'] = safe_float(upjong_per_em.text)
        
        shares = 0
        th_shares = soup_naver.find('th', string=re.compile('상장주식수'))
        if th_shares:
            td_shares = th_shares.find_next_sibling('td')
            if td_shares: shares = safe_float(td_shares.text)
            
        cop_table = soup_naver.select_one('div.cop_analysis table')
        if cop_table:
            for tr in cop_table.select('tbody tr'):
                th = tr.select_one('th')
                if th:
                    if '당기순이익' in th.text:
                        tds = tr.select('td')
                        if len(tds) >= 3: 
                            data['당기순이익'] = safe_float(tds[2].text) * 100000000 
                    elif 'BPS' in th.text:
                        tds = tr.select('td')
                        if len(tds) >= 3:
                            data['BPS'] = safe_float(tds[2].text)

        if data['BPS'] > 0 and shares > 0:
            data['자기자본'] = data['BPS'] * shares
            
    except Exception as e:
        pass

    # [STEP 2] 에프앤가이드 재무제표 원본 다이렉트 접속 (유동자산, 총부채 긁어오기!)
    fnguide_url = f"https://comp.fnguide.com/SVO2/ASP/SVD_Finance.asp?pGB=1&gicode=A{stock_code}"
    try:
        res_fn = requests.get(fnguide_url, headers=headers)
        soup_fn = BeautifulSoup(res_fn.text, 'html.parser')
        
        # 재무상태표 테이블 찾기
        div_bs = soup_fn.find('div', id='divDaechaY')
        if div_bs:
            for tr in div_bs.select('tbody tr'):
                th = tr.select_one('th')
                if th:
                    # 유동자산 (단위: 억원 -> 원)
                    if '유동자산' in th.text and '비유동자산' not in th.text:
                        tds = tr.select('td')
                        if len(tds) >= 3: # 최근 연도 값
                            data['유동자산'] = safe_float(tds[2].text) * 100000000
                    # 총부채 (부채총계)
                    elif '부채총계' in th.text:
                        tds = tr.select('td')
                        if len(tds) >= 3:
                            data['총부채'] = safe_float(tds[2].text) * 100000000
    except Exception as e:
        pass

    return data

# ==========================================
# 4. 스트림릿 UI 
# ==========================================
st.set_page_config(page_title="자동화 주식 스크리너", layout="wide")
st.title("🟩 퀀트 가치투자 스크리너 (풀버전 크롤링)")
st.markdown("유동자산, 총부채까지 완벽하게 긁어옵니다. 종목명을 붙여넣으세요.")

stock_input = st.text_area("종목명 입력", height=150)

if st.button("데이터 크롤링 및 분석 실행"):
    if not stock_input.strip():
        st.warning("종목명을 입력해주세요.")
    else:
        stock_names = [name.strip() for name in re.split(r'[\n\t, ]+', stock_input) if name.strip()]
        
        with st.spinner("심층 재무 데이터까지 탐색 중입니다... (조금 더 걸릴 수 있습니다)"):
            results = []
            progress_bar = st.progress(0)
            
            for idx, name in enumerate(stock_names):
                row = {
                    "종목명": name, "유동자산": 0, "총부채": 0, "BPS": 0, "업종PER": 0, 
                    "현재PER": 0, "PBR": 0, "EPS": 0, "당기순이익": 0, "자기자본": 0, "자사주": 0
                }
                
                stock_code = get_stock_code_from_naver(name)
                if stock_code:
                    crawled_data = fetch_finance_data(stock_code)
                    row.update(crawled_data)
                
                results.append(row)
                progress_bar.progress((idx + 1) / len(stock_names))
                
            df_result = pd.DataFrame(results)
            df_result = df_result[['종목명', '유동자산', '총부채', 'BPS', '업종PER', '현재PER', 'PBR', 'EPS', '당기순이익', '자기자본', '자사주']]
            
            st.success(f"총 {len(results)}개 종목 크롤링 완료!")
            
            st.dataframe(df_result.style.format({
                "유동자산": "{:,.0f}", "총부채": "{:,.0f}", "당기순이익": "{:,.0f}",
                "자기자본": "{:,.0f}", "자사주": "{:,.0f}", "BPS": "{:,.0f}", "EPS": "{:,.0f}",
                "업종PER": "{:.2f}", "현재PER": "{:.2f}", "PBR": "{:.2f}"
            }), use_container_width=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_result.to_excel(writer, index=False, sheet_name='Quant_Data')
            
            st.download_button(
                label="📥 엑셀(Excel) 다운로드",
                data=output.getvalue(),
                file_name=f"Quant_Data_{datetime.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
