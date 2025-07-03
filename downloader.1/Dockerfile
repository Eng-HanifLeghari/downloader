# ✅ Use official Python image
FROM python:3.11-slim

# Set working directory inside container
WORKDIR /downloader

# Copy requirements first
COPY requirements.txt .

# ✅ Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code
COPY . .

# Run the app (replace with your actual file if needed)
CMD ["python", "main.py"]
