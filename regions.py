"""
웹사이트에서 검색할 수 있는 지역 목록.

각 지역의 위도/경도(시청·도청 부근)를 기상청 격자 좌표(nx, ny)로 변환해 사용합니다.
지역을 추가하려면 REGIONS에 한 줄 추가하면 됩니다. (slug는 영문 소문자, 파일 이름으로 쓰임)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from weather_fetcher import latlon_to_grid


@dataclass(frozen=True)
class Region:
    slug: str       # 페이지 파일 이름 (busan → busan.html)
    name: str       # 화면에 보이는 이름
    province: str   # 시·도
    lat: float
    lon: float

    @property
    def grid(self) -> Tuple[int, int]:
        return latlon_to_grid(self.lat, self.lon)


REGIONS: List[Region] = [
    Region("seoul", "서울", "서울특별시", 37.5665, 126.9780),
    Region("incheon", "인천", "인천광역시", 37.4563, 126.7052),
    Region("suwon", "수원", "경기도", 37.2636, 127.0286),
    Region("seongnam", "성남", "경기도", 37.4200, 127.1267),
    Region("goyang", "고양", "경기도", 37.6584, 126.8320),
    Region("yongin", "용인", "경기도", 37.2411, 127.1776),
    Region("bucheon", "부천", "경기도", 37.5034, 126.7660),
    Region("ansan", "안산", "경기도", 37.3219, 126.8309),
    Region("hwaseong", "화성", "경기도", 37.1995, 126.8312),
    Region("pyeongtaek", "평택", "경기도", 36.9921, 127.1129),
    Region("uijeongbu", "의정부", "경기도", 37.7381, 127.0337),
    Region("paju", "파주", "경기도", 37.7599, 126.7800),
    Region("chuncheon", "춘천", "강원특별자치도", 37.8813, 127.7298),
    Region("wonju", "원주", "강원특별자치도", 37.3422, 127.9202),
    Region("gangneung", "강릉", "강원특별자치도", 37.7519, 128.8761),
    Region("sokcho", "속초", "강원특별자치도", 38.2070, 128.5918),
    Region("cheongju", "청주", "충청북도", 36.6424, 127.4890),
    Region("chungju", "충주", "충청북도", 36.9910, 127.9259),
    Region("daejeon", "대전", "대전광역시", 36.3504, 127.3845),
    Region("sejong", "세종", "세종특별자치시", 36.4800, 127.2890),
    Region("cheonan", "천안", "충청남도", 36.8151, 127.1139),
    Region("hongseong", "홍성", "충청남도", 36.6010, 126.6608),
    Region("jeonju", "전주", "전북특별자치도", 35.8242, 127.1480),
    Region("gunsan", "군산", "전북특별자치도", 35.9676, 126.7368),
    Region("iksan", "익산", "전북특별자치도", 35.9483, 126.9577),
    Region("gwangju", "광주", "광주광역시", 35.1595, 126.8526),
    Region("mokpo", "목포", "전라남도", 34.8118, 126.3922),
    Region("yeosu", "여수", "전라남도", 34.7604, 127.6622),
    Region("suncheon", "순천", "전라남도", 34.9506, 127.4872),
    Region("daegu", "대구", "대구광역시", 35.8714, 128.6014),
    Region("pohang", "포항", "경상북도", 36.0190, 129.3435),
    Region("gyeongju", "경주", "경상북도", 35.8562, 129.2247),
    Region("andong", "안동", "경상북도", 36.5684, 128.7294),
    Region("gumi", "구미", "경상북도", 36.1195, 128.3446),
    Region("ulleung", "울릉도", "경상북도", 37.4845, 130.9057),
    Region("dokdo", "독도", "경상북도", 37.2426, 131.8669),
    Region("busan", "부산", "부산광역시", 35.1796, 129.0756),
    Region("ulsan", "울산", "울산광역시", 35.5384, 129.3114),
    Region("changwon", "창원", "경상남도", 35.2281, 128.6811),
    Region("jinju", "진주", "경상남도", 35.1800, 128.1076),
    Region("gimhae", "김해", "경상남도", 35.2285, 128.8894),
    Region("jeju", "제주", "제주특별자치도", 33.4996, 126.5312),
    Region("seogwipo", "서귀포", "제주특별자치도", 33.2541, 126.5600),
]


# 시·도 → 권역 (웹사이트 '다른 지역 일교차'에서 칩으로 나눠 보여줄 때 사용)
PROVINCE_GROUPS = {
    "서울특별시": "수도권", "인천광역시": "수도권", "경기도": "수도권",
    "강원특별자치도": "강원",
    "충청북도": "충청", "충청남도": "충청", "대전광역시": "충청", "세종특별자치시": "충청",
    "전북특별자치도": "전라", "전라남도": "전라", "광주광역시": "전라",
    "경상북도": "경상", "경상남도": "경상", "대구광역시": "경상", "부산광역시": "경상", "울산광역시": "경상",
    "제주특별자치도": "제주",
}


def region_group(province: str) -> str:
    return PROVINCE_GROUPS.get(province, "기타")


def find_region(slug: str) -> Optional[Region]:
    return next((r for r in REGIONS if r.slug == slug), None)


def find_region_by_grid(nx: int, ny: int) -> Optional[Region]:
    return next((r for r in REGIONS if r.grid == (nx, ny)), None)
