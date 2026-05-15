import streamlit as st
import OpenDartReader
import pandas as pd
import re
from io import BytesIO

# 1. API 키 설정 (이미지에서 제공된 키 사용)
API_KEY = '0d3337714983152206d438906ff525000677118e'
dart = OpenDartReader(API_KEY)

st.set_page_config(page_title="기업개황 조회 서비스", layout="wide")

st.title("🏢 오픈다트 기업개황 조회")
st.info("기업명을 입력하면 전화번호, 팩스번호, 주소를 조회합니다. 여러 기업은 콤마(,)나 공백으로 구분하세요.")

# 2. 사용자 입력 (복수 입력 가능)
raw_input = st.text_area("조회할 기업명을 입력하세요", placeholder="예: 삼성전자, 현대자동차 SK하이닉스")

if st.button("데이터 조회 시작"):
    if not raw_input.strip():
        st.warning("기업명을 입력해주세요.")
    else:
        # 정규표현식을 사용하여 콤마, 공백, 줄바꿈을 기준으로 기업명 분리
        company_names = [name.strip() for name in re.split(r'[,\s\n]+', raw_input) if name.strip()]
        
        results = []
        progress_bar = st.progress(0)
        
        for i, name in enumerate(company_names):
            try:
                # 기업개황 정보 가져오기
                info = dart.company(name)
                
                if info:
                    results.append({
                        "기업명": info.get('corp_name', name),
                        "전화번호": info.get('phn_no', '-'),
                        "팩스번호": info.get('fax_no', '-'),
                        "주소": info.get('adres', '-')
                    })
                else:
                    results.append({"기업명": name, "전화번호": "미검색", "팩스번호": "미검색", "주소": "검색 결과 없음"})
            
            except Exception as e:
                results.append({"기업명": name, "전화번호": "에러", "팩스번호": "에러", "주소": f"조회 실패 ({str(e)})"})
            
            progress_bar.progress((i + 1) / len(company_names))

        # 3. 결과 테이블 표시
        df = pd.DataFrame(results)
        st.subheader("🔍 조회 결과")
        st.dataframe(df, use_container_width=True)

        # 4. 엑셀 파일 다운로드 기능
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='기업개황_조회')
        
        excel_data = output.getvalue()
        
        st.download_button(
            label="📂 엑셀 파일 다운로드",
            data=excel_data,
            file_name="기업개황_조회결과.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
