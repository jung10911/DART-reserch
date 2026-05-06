import streamlit as st
import pandas as pd
import yfinance as yf
import FinanceDataReader as fdr
import io
import re

st.set_page_config(page_title="야후파이낸스 재무 추출기", layout="wide")

# [1] 한국 주식 이름 -> 야후 파이낸스용 티커 변환기 (자동화)
@st.cache_data
def load_tickers():
    df_kospi = fdr.StockListing('KOSPI')
    df_kosdaq = fdr.StockListing('KOSDAQ')
    
    ticker_map = {}
    # 코스피는 .KS, 코스닥은 .KQ를 붙여줍니다.
    for _, row in df_kospi.iterrows():
        ticker_map[row['Name']] = f"{row['Code']}.KS"
    for _, row in df_kosdaq.iterrows():
        ticker_map[row['Name']] = f"{row['Code']}.KQ"
    return ticker_map

# [2] 야후 파이낸스 데이터 추출 함수
def get_yf_data(stock_name, ticker_map):
    data = {
        '종목명': stock_name, '유동자산': '0', '총부채': '0', 'BPS': '0', 
        '현재PER': '0', 'PBR': '0', 'EPS': '0', '당기순이익': '0', '자기자본': '0'
    }
    
    ticker = ticker_map.get(stock_name)
    if not ticker:
        return data 

    try:
        stock = yf.Ticker(ticker)
        
        # 1. 요약 정보(info)에서 핵심 지표 추출
        info = stock.info
        data['현재PER'] = info.get('trailingPE', '0')
        data['PBR'] = info.get('priceToBook', '0')
        data['EPS'] = info.get('trailingEps', '0')
        data['BPS'] = info.get('bookValue', '0')
        data['총부채'] = info.get('totalDebt', '0')
        data['당기순이익'] = info.get('netIncomeToCommon', '0')

        # 2. 재무상태표(balance_sheet)에서 자산/자본 추출
        bs = stock.balance_sheet
        if not bs.empty:
            # 영어로 된 계정과목을 매칭 (야후 파이낸스는 영문 기준)
            if 'Current Assets' in bs.index:
                data['유동자산'] = bs.loc['Current Assets'].iloc[0]
            if 'Stockholders Equity' in bs.index:
                data['자기자본'] = bs.loc['Stockholders Equity'].iloc[0]

    except Exception:
        pass # 오류 발생 시 기본값 0 유지

    return data

# [3] 스트림릿 화면 구성
st.title("🌎 글로벌 & 국내 주식 재무 추출기 (Yahoo Finance)")
st.markdown("**기업명(삼성전자, 카카오 등)을 줄바꿈으로 입력하세요. 야후 서버에서 즉시 데이터를 긁어옵니다.**")

ticker_map = load_tickers()
user_input = st.text_area("기업명 입력창", height=150, placeholder="삼성전자\nSK하이닉스\n에코프로")

if st.button("🚀 야후 파이낸스 데이터 추출"):
    if user_input:
        with st.spinner("야후 파이낸스 글로벌 서버와 통신 중입니다..."):
            corp_list = [c.strip() for c in re.split(r'[\n\s]+', user_input.strip()) if c.strip()]
            
            results = [get_yf_data(corp, ticker_map) for corp in corp_list]
                
            df = pd.DataFrame(results)
# 숫자가 너무 크므로 보기 편하게 쉼표(,) 포맷팅 추가
            numeric_cols = ['유동자산', '총부채', '당기순이익', '자기자본']
            for col in numeric_cols:
                # 에러 발생 시 강제로 빈값(NaN) 처리 후 0으로 채움
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
            st.success("데이터 추출 완료! (야후 파이낸스는 업종PER 및 자사주 데이터를 기본 제공하지 않아 제외되었습니다.)")
            st.dataframe(df)
            
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='야후재무정보')
            
            st.download_button(
                label="📥 엑셀로 다운로드", 
                data=excel_buffer.getvalue(), 
                file_name="야후파이낸스_추출결과.xlsx", 
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    else:
        st.warning("기업명을 입력해 주세요.")
