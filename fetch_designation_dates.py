# -*- coding: utf-8 -*-
"""
국가유산청(cha.go.kr) 오픈API로 국보·보물(840건) 지정일자(ccbaAsdt)와
대표 이미지 URL을 수집하여 heritage_data.csv 에 designation_date / image_url
컬럼으로 추가하는 스크립트.
※ 이 API는 공공데이터포털 인증키가 필요 없습니다 (URL만으로 바로 호출 가능).

동작 방식:
0. heritage_data.csv 를 먼저 읽어 (category_code, designation_no) 대상 목록(840건) 확보
   ※ 국가유산청 전체 목록은 국보 372건 + 보물 2564건(총 2936건)으로 heritage_data.csv
     보다 훨씬 많으므로, 목록 전체가 아니라 CSV에 있는 840건에 대해서만 상세조회/이미지
     API를 호출한다.
1. 목록 API(SearchKindOpenapiList.do)를 ccbaKdcd=11(국보), 12(보물) 각각에 대해
   페이지네이션하며 호출 -> 각 항목의 ccbaKdcd/ccbaCtcd/ccbaAsno/ccbaCpno 확보
2. 위 목록 중 0단계의 대상(840건)에 해당하는 항목만 추려서
   상세조회 API(SearchKindOpenapiDt.do) 호출 -> ccbaAsdt(지정일자) 확보
3. 같은 대상 항목에 대해 이미지검색 API(SearchImageOpenapi.do)를
   ccbaKdcd/ccbaCtcd/ccbaAsno로 호출 -> 첫 번째(sn=1) 이미지를 대표 이미지로 사용해
   image_url 확보
4. heritage_data.csv 의 category_code/designation_no 기준으로 매칭하여
   designation_date / image_url 컬럼을 추가한 heritage_data_with_date.csv 로 저장
"""

import re
import time
import xml.etree.ElementTree as ET

import pandas as pd
import requests

LIST_URL = "https://www.cha.go.kr/cha/SearchKindOpenapiList.do"
DETAIL_URL = "https://www.cha.go.kr/cha/SearchKindOpenapiDt.do"
IMAGE_URL = "https://www.cha.go.kr/cha/SearchImageOpenapi.do"

INPUT_CSV = "heritage_data.csv"
OUTPUT_CSV = "heritage_data_with_date.csv"

KDCD_LIST = [11, 12]  # 11=국보, 12=보물


MAX_RETRIES = 5
RETRY_BACKOFF_SEC = 3


def _get_with_retry(url, params):
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.encoding = "utf-8"
            return resp.text
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_SEC * attempt
                print(f"    [재시도 {attempt}/{MAX_RETRIES}] {e.__class__.__name__} -> {wait}초 후 재시도")
                time.sleep(wait)
    raise last_exc


def fetch_list(ccba_kdcd, page_index=1, page_unit=100):
    params = {"ccbaKdcd": ccba_kdcd, "pageIndex": page_index, "pageUnit": page_unit}
    return _get_with_retry(LIST_URL, params)


def fetch_detail(ccba_kdcd, ccba_ctcd, ccba_asno, ccba_cpno):
    params = {
        "ccbaKdcd": ccba_kdcd,
        "ccbaCtcd": ccba_ctcd,
        "ccbaAsno": ccba_asno,
        "ccbaCpno": ccba_cpno,
    }
    return _get_with_retry(DETAIL_URL, params)


def fetch_image(ccba_kdcd, ccba_ctcd, ccba_asno):
    params = {
        "ccbaKdcd": ccba_kdcd,
        "ccbaCtcd": ccba_ctcd,
        "ccbaAsno": ccba_asno,
    }
    return _get_with_retry(IMAGE_URL, params)


def parse_list_items(xml_text):
    root = ET.fromstring(xml_text)
    items = []
    for item in root.findall(".//item"):
        items.append({child.tag: (child.text or "").strip() for child in item})
    return items


def parse_detail_date(xml_text):
    root = ET.fromstring(xml_text)
    node = root.find(".//ccbaAsdt")
    if node is not None and node.text:
        return node.text.strip()
    return ""


def parse_representative_image(xml_text):
    """이미지검색 API 응답에서 첫 번째(sn=1) imageUrl을 대표 이미지로 반환.
    일부 항목은 ccimDesc(설명)에 CDATA로 감싸지지 않은 '<','>' 문자가 섞여
    XML 자체가 깨져서 오므로, 정규식으로 첫 번째 <imageUrl> 값만 직접 추출한다."""
    match = re.search(r"<imageUrl>(.*?)</imageUrl>", xml_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def collect_all_list_items():
    all_items = []
    for kdcd in KDCD_LIST:
        page = 1
        while True:
            xml_text = fetch_list(kdcd, page_index=page, page_unit=100)
            items = parse_list_items(xml_text)
            if not items:
                break
            all_items.extend(items)
            print(f"[목록] 종목코드 {kdcd} - {page}페이지: {len(items)}건 (누적 {len(all_items)}건)")
            page += 1
            time.sleep(0.2)
            if page > 50:  # 안전장치 (kdcd=12 보물 전체 2564건 기준 26페이지 필요, 여유있게 상향)
                break
    return all_items


def main():
    print("=== 0단계: heritage_data.csv 에서 대상 840건의 (category_code, designation_no) 추출 ===")
    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")
    target_keys = set(zip(df["category_code"].astype(int), df["designation_no"].astype(int)))
    print(f"대상 {len(target_keys)}건 확인\n")

    print("=== 1단계: 목록 API로 전체 국보·보물 항목 수집 ===")
    list_items = collect_all_list_items()
    print(f"총 {len(list_items)}건 수집 완료\n")

    print("=== 1.5단계: 대상 840건에 해당하는 항목만 필터링 ===")
    target_items = []
    for item in list_items:
        kdcd = item.get("ccbaKdcd")
        asno = item.get("ccbaAsno")
        if not (kdcd and asno):
            continue
        try:
            key = (int(kdcd), int(asno) // 10**7)
        except ValueError:
            continue
        if key in target_keys:
            target_items.append(item)
    print(f"목록 {len(list_items)}건 중 대상과 일치하는 {len(target_items)}건 필터링 완료")
    if len(target_items) != len(target_keys):
        print(f"  주의: 대상 {len(target_keys)}건 중 {len(target_keys) - len(target_items)}건은 목록에서 찾지 못함")
    print()

    print("=== 2단계: 상세조회 API(지정일자) + 이미지검색 API(대표 이미지) 항목별 수집 ===")
    date_map = {}  # key: (ccbaKdcd, designation_no) -> ccbaAsdt
    image_map = {}  # key: (ccbaKdcd, designation_no) -> image_url
    fail_list = []
    for idx, item in enumerate(target_items, start=1):
        kdcd = item.get("ccbaKdcd")
        ctcd = item.get("ccbaCtcd")
        asno = item.get("ccbaAsno")
        cpno = item.get("ccbaCpno")
        name = item.get("ccbaMnm1", "")

        if not (kdcd and ctcd and asno and cpno):
            fail_list.append((name, "목록 항목에 필수 파라미터 없음"))
            continue

        try:
            designation_no = int(asno) // 10**7
        except ValueError:
            designation_no = None

        asdt = ""
        try:
            xml_text = fetch_detail(kdcd, ctcd, asno, cpno)
            asdt = parse_detail_date(xml_text)
        except Exception as e:
            fail_list.append((name, f"상세조회 실패: {e}"))

        image_url = ""
        try:
            image_xml_text = fetch_image(kdcd, ctcd, asno)
            image_url = parse_representative_image(image_xml_text)
        except Exception as e:
            fail_list.append((name, f"이미지검색 실패: {e}"))

        if designation_no is not None:
            date_map[(int(kdcd), designation_no)] = asdt
            image_map[(int(kdcd), designation_no)] = image_url

        if idx % 20 == 0 or idx == len(target_items):
            print(f"  진행: {idx}/{len(target_items)}건 처리 (최근: {name} -> {asdt or '날짜없음'} / {'이미지있음' if image_url else '이미지없음'})")
        time.sleep(0.15)

    print(f"\n수집 완료: {len(date_map)}건 매칭 정보 확보, 실패(부분포함) {len(fail_list)}건")
    if fail_list:
        print("실패 목록(최대 10건 표시):")
        for name, reason in fail_list[:10]:
            print(f"  - {name}: {reason}")

    print("\n=== 3단계: heritage_data.csv 와 매칭하여 designation_date / image_url 컬럼 추가 ===")

    def lookup_date(row):
        key = (int(row["category_code"]), int(row["designation_no"]))
        return date_map.get(key, "")

    def lookup_image(row):
        key = (int(row["category_code"]), int(row["designation_no"]))
        return image_map.get(key, "")

    df["designation_date"] = df.apply(lookup_date, axis=1)
    df["image_url"] = df.apply(lookup_image, axis=1)

    matched_date = (df["designation_date"] != "").sum()
    matched_image = (df["image_url"] != "").sum()
    print(f"CSV {len(df)}건 중 designation_date {matched_date}건, image_url {matched_image}건 매칭 완료")

    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n완료: {OUTPUT_CSV} 저장")


if __name__ == "__main__":
    main()
