FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 NODE_FILES_DIR=/app/node
COPY panel/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY panel/app ./app
COPY node ./node
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
