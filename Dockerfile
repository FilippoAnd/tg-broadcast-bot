FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8080
CMD python3 bot.py & python3 -m http.server 8080CMD python3 bot.py & python3 -m http.server 8080
