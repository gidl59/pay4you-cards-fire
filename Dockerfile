FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

ENV PYTHONUNBUFFERED=1
ENV PORT=10000

CMD ["gunicorn","-b","0.0.0.0:10000","app:app"]
