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


def is_valid_route(
    origin: str,
    destination: str,
    departure_time: datetime,
    max_total_min: int = 210,
    max_wait_min: int = 80,
    allow_night_bus: bool = True,
    require_subway: bool = False,
) -> bool:
    """
    해당 시간에 유효한 경로가 있는지 확인.

    막차 끊김 판단 기준:
    1. 총 소요시간 > 210분 (3시간 30분)
    2. 출발 대기시간 > 80분 (첫차 기다리는 중)
    3. allow_night_bus=False면 심야버스 경로 제외
    4. require_subway=True면 지하철이 포함되어야 함
    """
    result = get_transit_route(origin, destination, departure_time)
    if not result or "routes" not in result or len(result["routes"]) == 0:
        return False

    # 심야버스 제외 옵션
    if not allow_night_bus and has_night_bus(result):
        return False

    # 지하철 필수 옵션
    if require_subway and not has_subway(result):
        return False

    arrival = get_arrival_time(result)
    first_dep = get_first_departure_time(result)

    if not arrival:
        return False

    # 총 소요시간 체크
    total_duration = (arrival - departure_time).total_seconds() / 60
    if total_duration > max_total_min:
        return False

    # 출발 대기시간 체크
    if first_dep:
        wait_time = (first_dep - departure_time).total_seconds() / 60
        if wait_time > max_wait_min:
            return False

    return True


def get_route_duration(origin: str, destination: str, departure_time: datetime) -> int | None:
    """특정 시간 출발 경로의 소요시간(분) 반환"""
    result = get_transit_route(origin, destination, departure_time)
    if not result or "routes" not in result:
        return None
    arrival = get_arrival_time(result)
    if not arrival:
        return None
    return int((arrival - departure_time).total_seconds() / 60)


def find_last_train_time(
    origin: str,
    destination: str,
    require_subway: bool = False,
) -> tuple[datetime | None, int | None]:
    """이분탐색으로 막차 시간 찾기 (약 5분 정확도). (시간, 소요시간) 반환"""
    now = datetime.now(KST)

    # 탐색 범위: 20:30 ~ 02:00
    if now.hour >= 20:
        start_8pm = now.replace(hour=20, minute=30, second=0, microsecond=0)
        end_2am = (now + timedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)
    elif now.hour < 2:
        start_8pm = (now - timedelta(days=1)).replace(hour=20, minute=30, second=0, microsecond=0)
        end_2am = now.replace(hour=2, minute=0, second=0, microsecond=0)
    else:
        start_8pm = now.replace(hour=20, minute=30, second=0, microsecond=0)
        end_2am = (now + timedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)

    left = start_8pm
    right = end_2am

    # 현재 시간에 경로가 없으면 이미 막차 끊김
    if not is_valid_route(origin, destination, now, require_subway=require_subway):
        return None, None

    # 새벽 2시에도 유효한 경로가 있으면 그냥 반환
    if is_valid_route(origin, destination, right, require_subway=require_subway):
        duration = get_route_duration(origin, destination, right)
        return right, duration

    # 이분탐색 (6회 = 약 5분 정확도)
    for _ in range(6):
        mid = left + (right - left) / 2
        if is_valid_route(origin, destination, mid, require_subway=require_subway):
            left = mid
        else:
            right = mid

    duration = get_route_duration(origin, destination, left)
    return left, duration


def find_recommended_time(origin: str, destination: str) -> tuple[datetime | None, int | None]:
    """소요시간이 급증하기 전 추천 출발 시간 찾기"""
    now = datetime.now(KST)

    # 탐색 범위 설정
    if now.hour >= 20:
        start = now
        end = (now + timedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)
    elif now.hour < 2:
        start = now
        end = now.replace(hour=2, minute=0, second=0, microsecond=0)
    else:
        start = now.replace(hour=20, minute=30, second=0, microsecond=0)
        end = (now + timedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)

    # 기준 소요시간 (현재 또는 20:30 출발)
    base_duration = get_route_duration(origin, destination, start)
    if not base_duration:
        return None, None

    # 30분 간격으로 체크하면서 소요시간 급증 시점 찾기
    best_time = start
    best_duration = base_duration
    check_time = start

    while check_time < end:
        duration = get_route_duration(origin, destination, check_time)
        if duration is None:
            break

        # 소요시간이 기준의 1.5배 이상이면 급증으로 판단
        if duration > base_duration * 1.5:
            break

        best_time = check_time
        best_duration = duration
        check_time += timedelta(minutes=30)

    return best_time, best_duration


def find_all_last_trains(origin: str, destination: str) -> dict:
    """세 가지 막차 정보 찾기"""
    # 1. 지하철 포함 (지하철이 하나라도 있어야 함)
    subway_time, subway_dur = find_last_train_time(origin, destination, require_subway=True)

    # 2. 아무거나 (심야버스 포함)
    any_time, any_dur = find_last_train_time(origin, destination, require_subway=False)

    # 3. 추천 출발 시간
    rec_time, rec_dur = find_recommended_time(origin, destination)

    return {
        "subway": (subway_time, subway_dur),
        "any": (any_time, any_dur),
        "recommended": (rec_time, rec_dur),
    }


@mcp.tool()
def analyze_escape_plan(origin: str, destination: str) -> str:
    """
    출발지와 목적지를 입력받아,
    막차 시간을 '막차지킴이'가 분석해줍니다.
    예시 입력: origin="인천대입구역", destination="강남역"
    """
    now = datetime.now(KST)

    # 1. 현재 경로 검색
    data = get_transit_route(origin, destination, now)

    if not data or "routes" not in data or len(data["routes"]) == 0:
        return f"""
🛡️ [막차지킴이 LastGuardian]

❌ '{origin}' → '{destination}' 경로를 찾을 수 없습니다.

가능한 원인:
- 이미 막차가 끊겼습니다 🚫
- 주소를 더 정확하게 입력해주세요 (예: "강남역", "서울역")
- 대중교통으로 갈 수 없는 거리입니다
"""

    # 2. 경로 정보 추출
    route = data["routes"][0]
    distance_m = route.get("distanceMeters", 0)

    # 2-1. 노선 정보 추출
    transit_steps = extract_route_summary(data)

    # 3. 막차 시간 찾기
    last_trains = find_all_last_trains(origin, destination)

    subway_time, subway_dur = last_trains["subway"]
    any_time, any_dur = last_trains["any"]
    rec_time, rec_dur = last_trains["recommended"]

    # 막차 다 끊겼으면 추천 출발도 무의미
    if any_time is None:
        rec_time, rec_dur = None, None

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
    mcp.run()
