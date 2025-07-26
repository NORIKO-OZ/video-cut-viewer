FROM python:3.11-slim

# システムパッケージのアップデートとFFmpegのインストール
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && ffmpeg -version

WORKDIR /app

# 依存関係をインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションファイルをコピー
COPY . .

# ポートを設定
ENV PORT=8000
EXPOSE $PORT

# FFmpegが正しくインストールされているかテスト
RUN which ffmpeg && ffmpeg -version

# アプリケーションを起動
CMD ["python", "app_simple.py"]