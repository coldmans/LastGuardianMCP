FROM python:3.11-slim

WORKDIR /app

# 의존성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY last-guardian.py .

# Railway는 PORT 환경 변수를 자동으로 주입
ENV PORT=8000

# 서버 실행
CMD ["python", "last-guardian.py"]
