# ... other Dockerfile commands ...

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

# Now you can run your pip3 install command
COPY requirements.txt .
RUN pip3 install -r requirements.txt