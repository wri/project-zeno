FROM python

WORKDIR /app

COPY requirements.txt .

RUN pip install -r requirements.txt

# Copy the dataset ingestion code and entrypoint script
COPY datasets/ ./datasets/
COPY entrypoint.sh .

RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
