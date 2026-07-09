# Vigil — API + UI in one container.
# First boot builds the pgvector RAG corpus (~906 chunks; needs OPENAI_API_KEY)
# and trains the Isolation Forest from the committed training split — both are
# idempotent, so restarts are fast.

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
