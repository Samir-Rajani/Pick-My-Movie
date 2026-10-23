FROM python:3.12-slim
WORKDIR /app
COPY app.py recommender.py ./
COPY web ./web
COPY data ./data
ENV HOST=0.0.0.0 PORT=8000 PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "app.py"]
