# -*- coding: utf-8 -*-
"""
국가유산청(cha.go.kr) 자체 오픈API로 국보/보물의 지정일자를 수집하는 스크립트.
※ 이 API는 공공데이터포털 인증키가 필요 없습니다 (URL만으로 바로 호출 가능).

사용법:
1. pip install requests pandas
2. 먼저 TEST_MODE = True 로 실행해서 응답 구조(필드명)를 확인하세요.
3. 확인되면 TEST_MODE = False 로 바꿔 전체 실행하세요.
4. 이 채팅 서버는 외부 API 호출이 막혀 있어, 본인 컴�터 또는 Claude Code에서 실행해야 합니다.
"""

import requests
import pandas as pd
import time
import xml.etree.ElementTree as ET

TEST_MODE = True
INPUT_CSV = "국보_보물_위치정보.csv"
OUTPUT_CSV = "국보_보물_지정일자_추가.csv"

LIST_URL = "https://www.cha.go.kr/cha/SearchKindOpenapiList.do"

def fetch_list(ccba_kdcd, ccba_ctcd=None, page_index=1, page_unit=100):
    """종목코드(ccbaKdcd) 기준으로 목록을 가져옴. 시도코드(ccbaCtcd) 생략 시 전국 대상."""
    params = {
        "ccbaKdcd": ccba_kdcd,
        "pageUnit": page_unit,
        "pageIndex": page_index,
    }
    if ccba_ctcd:
        params["ccbaCtcd"] = ccba_ctcd
    resp = requests.get(LIST_URL, params=params, timeout=10)
    resp.encoding = 'utf-8'
    return resp.text

def parse_items(xml_text):
    root = ET.fromstring(xml_text)
    items = []
    for item in root.findall(".//item"):
        items.append({child.tag: (child.text or "").strip() for child in item})
    return items

def main():
    if TEST_MODE:
        print("=== 테스트: 국보(종목코드 11) 1페이지 조회 ===")
        xml_text = fetch_list(ccba_kdcd=11, page_index=1, page_unit=5)
        print("--- 원본 XML(앞부분) ---")
        print(xml_text[:1500])
        items = parse_items(xml_text)
        print(f"\n파싱된 항목 수: {len(items)}")
        if items:
            print("첫 항목 필드 확인:")
            for k, v in items[0].items():
                print(f"  {k}: {v}")
        print("\n위에서 지정일자로 보이는 필드명을 확인한 뒤 스크립트의 DATE_FIELD 값을 맞추고, TEST_MODE=False로 바꿔 전체 실행하세요.")
        return

    DATE_FIELD = "ccbaAsdt"  # 테스트 결과 보고 실제 필드명으로 수정 필요할 수 있음

    all_items = []
    for kdcd in [11, 12]:  # 11=국보, 12=보물
        page = 1
        while True:
            xml_text = fetch_list(ccba_kdcd=kdcd, page_index=page, page_unit=100)
            items = parse_items(xml_text)
            if not items:
                break
            all_items.extend(items)
            print(f"종목코드 {kdcd} - {page}페이지: {len(items)}건 수집 (누적 {len(all_items)}건)")
            page += 1
            time.sleep(0.2)
            if page > 20:  # 안전장치
                break

    result_df = pd.DataFrame(all_items)
    result_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n완료: 총 {len(result_df)}건을 {OUTPUT_CSV}에 저장했습니다.")

if __name__ == "__main__":
    main()
