import os
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastmcp import FastMCP
from dotenv import load_dotenv

# .env 로드
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# LastGuardian (막차지킴이)
mcp = FastMCP("LastGuardian")

# 한국 시간대
KST = ZoneInfo("Asia/Seoul")


def get_transit_route(origin: str, destination: str, departure_time: datetime = None):
    """Google Routes API: 대중교통 경로 검색"""
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"

    if departure_time is None:
        departure_time = datetime.now(KST)

    departure_str = departure_time.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = {
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": "TRANSIT",
        "departureTime": departure_str,
        "languageCode": "ko",
        "regionCode": "KR",
    }

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.legs.steps",
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None


def extract_route_summary(route_data: dict) -> list[dict]:
    """경로에서 탑승할 교통수단 정보 추출"""
    transit_info = []
    try:
        steps = route_data["routes"][0]["legs"][0]["steps"]
        for step in steps:
            td = step.get("transitDetails")
            if td:
                line = td.get("transitLine", {})
                stops = td.get("stopDetails", {})

                vehicle_type = line.get("vehicle", {}).get("type", "TRANSIT")
                vehicle_icon = {"BUS": "🚌", "SUBWAY": "🚇", "RAIL": "🚆"}.get(vehicle_type, "🚃")

                info = {
                    "icon": vehicle_icon,
                    "line": line.get("nameShort") or line.get("name", "?"),
                    "departure": stops.get("departureStop", {}).get("name", "?"),
                    "arrival": stops.get("arrivalStop", {}).get("name", "?"),
                }
                transit_info.append(info)
    except (KeyError, IndexError):
        pass
    return transit_info


def parse_transit_time(time_str: str) -> datetime | None:
    """UTC 시간 문자열을 KST datetime으로 변환"""
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ")
        return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(KST)
    except (ValueError, TypeError):
        return None


def get_first_departure_time(route_data: dict) -> datetime | None:
    """경로 데이터에서 첫 번째 대중교통 출발 시간 추출"""
    try:
        steps = route_data["routes"][0]["legs"][0]["steps"]
        for step in steps:
            td = step.get("transitDetails")
            if td and "stopDetails" in td:
                dep_str = td["stopDetails"].get("departureTime")
                if dep_str:
                    return parse_transit_time(dep_str)
    except (KeyError, IndexError):
        pass
    return None


def get_arrival_time(route_data: dict) -> datetime | None:
    """경로 데이터에서 마지막 도착 시간 추출"""
    try:
        steps = route_data["routes"][0]["legs"][0]["steps"]
        for step in reversed(steps):
            td = step.get("transitDetails")
            if td and "stopDetails" in td:
                arr_str = td["stopDetails"].get("arrivalTime")
                if arr_str:
                    return parse_transit_time(arr_str)
    except (KeyError, IndexError):
        pass
    return None


def has_night_bus(route_data: dict) -> bool:
    """경로에 심야버스(N버스)가 포함되어 있는지 확인"""
    try:
        steps = route_data["routes"][0]["legs"][0]["steps"]
        for step in steps:
            td = step.get("transitDetails")
            if td:
                line = td.get("transitLine", {})
                name = line.get("nameShort") or line.get("name", "")
                vehicle_type = line.get("vehicle", {}).get("type", "")
                # N으로 시작하는 버스 = 심야버스
                if vehicle_type == "BUS" and name.startswith("N"):
                    return True
    except (KeyError, IndexError):
        pass
    return False


def has_subway(route_data: dict) -> bool:
    """경로에 지하철이 포함되어 있는지 확인"""
    try:
        steps = route_data["routes"][0]["legs"][0]["steps"]
        for step in steps:
            td = step.get("transitDetails")
            if td:
                line = td.get("transitLine", {})
                vehicle_type = line.get("vehicle", {}).get("type", "")
                if vehicle_type in ("SUBWAY", "RAIL"):
                    return True
    except (KeyError, IndexError):
        pass
    return False


def analyze_route_data(
    route_data: dict,
    departure_time: datetime,
    max_total_min: int = 210,
    max_wait_min: int = 80,
) -> tuple[bool, bool, int | None]:
    """
    경로 데이터 분석: (유효여부, 지하철포함여부, 소요시간) 반환.
    API 호출 없이 이미 받은 데이터만 분석.
    """
    if not route_data or "routes" not in route_data or len(route_data["routes"]) == 0:
        return False, False, None

    arrival = get_arrival_time(route_data)
    first_dep = get_first_departure_time(route_data)

    if not arrival:
        return False, False, None

    duration = int((arrival - departure_time).total_seconds() / 60)

    # 총 소요시간 체크
    if duration > max_total_min:
        return False, False, None

    # 출발 대기시간 체크
    if first_dep:
        wait_time = (first_dep - departure_time).total_seconds() / 60
        if wait_time > max_wait_min:
            return False, False, None

    has_sub = has_subway(route_data)
    return True, has_sub, duration


def find_all_last_trains(origin: str, destination: str) -> tuple[dict, dict | None]:
    """
    한 번의 이분탐색으로 모든 막차 정보 찾기.
    API 호출: 최대 7회 (현재 1회 + 이분탐색 6회)

    Returns:
        (막차정보 dict, 현재경로 데이터 or None)
    """
    now = datetime.now(KST)

    # 탐색 범위: 20:30 ~ 02:00
    if now.hour >= 20:
        start = now.replace(hour=20, minute=30, second=0, microsecond=0)
        end = (now + timedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)
    elif now.hour < 2:
        start = (now - timedelta(days=1)).replace(hour=20, minute=30, second=0, microsecond=0)
        end = now.replace(hour=2, minute=0, second=0, microsecond=0)
    else:
        start = now.replace(hour=20, minute=30, second=0, microsecond=0)
        end = (now + timedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)

    # 결과 저장
    last_subway = (None, None)  # (time, duration)
    last_any = (None, None)
    recommended = (None, None)
    base_duration = None

    # 1. 현재 시간 체크 (API 호출 1회)
    now_data = get_transit_route(origin, destination, now)

    # 경로 자체가 없으면 (주소 오류 등)
    if not now_data or "routes" not in now_data or len(now_data["routes"]) == 0:
        return {"subway": (None, None), "any": (None, None), "recommended": (None, None)}, None

    is_valid, has_sub, duration = analyze_route_data(now_data, now)

    if not is_valid:
        # 경로는 있지만 막차 끊김 (소요시간 초과)
        return {"subway": (None, None), "any": (None, None), "recommended": (None, None)}, now_data

    # 현재 경로 정보 저장
    base_duration = duration
    last_any = (now, duration)
    recommended = (now, duration)
    if has_sub:
        last_subway = (now, duration)

    # 2. 이분탐색 (API 호출 6회)
    left, right = start, end

    for _ in range(6):
        mid = left + (right - left) / 2
        mid_data = get_transit_route(origin, destination, mid)
        is_valid, has_sub, duration = analyze_route_data(mid_data, mid)

        if is_valid:
            left = mid
            last_any = (mid, duration)

            if has_sub:
                last_subway = (mid, duration)

            # 추천 시간: 소요시간이 기준의 1.5배 미만이면 갱신
            if base_duration and duration < base_duration * 1.5:
                recommended = (mid, duration)
        else:
            right = mid

    return {
        "subway": last_subway,
        "any": last_any,
        "recommended": recommended,
    }, now_data


@mcp.tool()
def analyze_escape_plan(origin: str, destination: str) -> str:
    """
    출발지와 목적지를 입력받아,
    막차 시간을 '막차지킴이'가 분석해줍니다.
    예시 입력: origin="인천대입구역", destination="강남역"
    """
    now = datetime.now(KST)

    # 막차 시간 찾기 (API 호출: 현재 1회 + 이분탐색 최대 6회)
    last_trains, current_route = find_all_last_trains(origin, destination)

    # 경로 자체가 없으면 (주소 오류)
    if current_route is None:
        return f"""
🛡️ [막차지킴이 LastGuardian]

❌ '{origin}' → '{destination}' 경로를 찾을 수 없습니다.

가능한 원인:
- 주소를 더 정확하게 입력해주세요 (예: "강남역", "서울역")
- 대중교통으로 갈 수 없는 거리입니다
"""

    subway_time, subway_dur = last_trains["subway"]
    any_time, any_dur = last_trains["any"]
    rec_time, rec_dur = last_trains["recommended"]

    # 현재 경로 정보 (API 추가 호출 없이 재사용)
    route = current_route["routes"][0]
    distance_m = route.get("distanceMeters", 0)
    transit_steps = extract_route_summary(current_route)

    # 4. 남은 시간 계산
    def format_time_info(time, dur):
        if time:
            left = int((time - now).total_seconds() // 60)
            return f"**{time.strftime('%H:%M')}** ({dur}분 소요, {left}분 남음)"
        return "끊김"

    subway_str = format_time_info(subway_time, subway_dur)
    any_str = format_time_info(any_time, any_dur)
    rec_str = format_time_info(rec_time, rec_dur)

    # 5. 긴박도 판단
    subway_left = int((subway_time - now).total_seconds() // 60) if subway_time else 0
    any_left = int((any_time - now).total_seconds() // 60) if any_time else 0

    if subway_left <= 0:
        if any_left > 0:
            urgency = "🚇 지하철 끊김! 버스로 가세요!"
            advice = f"막차까지 **{any_left}분** 남았습니다."
        else:
            urgency = "🚨 전부 끊김!"
            advice = "오늘은 대중교통 못 타요. 내일 첫차를 노리세요."
    elif subway_left <= 10:
        urgency = "🔥🔥🔥 지금 당장 뛰세요!!!"
        advice = f"지하철 막차까지 **{subway_left}분**! 폰 보지 말고 뛰어요!"
    elif subway_left <= 30:
        urgency = "⚠️ 서두르세요!"
        advice = f"지하철까지 **{subway_left}분** 남았습니다. 지금 나가세요!"
    else:
        urgency = "⏰ 아직 여유 있음"
        advice = f"지하철까지 **{subway_left}분** 남았지만, 미루다 후회합니다."

    # 노선 정보 문자열 생성
    route_lines = []
    for t in transit_steps:
        route_lines.append(f"{t['icon']} {t['line']}: {t['departure']} → {t['arrival']}")
    route_info = "\n".join(route_lines) if route_lines else "정보 없음"

    result = f"""
🛡️ [막차지킴이 LastGuardian]

📍 경로: {origin} → {destination}
📏 거리: {distance_m / 1000:.1f}km

🎫 현재 추천 경로:
{route_info}

⏰ 막차 정보 (±5분):
🚇 지하철 포함: {subway_str}
🚌 아무거나: {any_str}
⭐ 추천 출발: {rec_str}

{urgency}
{advice}
"""

    return result


if __name__ == "__main__":
    # Railway 배포를 위한 HTTP 서버 모드
    import uvicorn
    import os

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(mcp.get_asgi_app(), host="0.0.0.0", port=port)
