# ── Dockerfile ────────────────────────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app
# install deps first (for layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# copy the Streamlit app
COPY . .
# run the app
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
