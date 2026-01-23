FROM python:3.11

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libvirt-clients \
    libvirt-dev \
    qemu-utils \
    virtinst \
    genisoimage \
    openssh-client \
    gcc \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# IMPORTANT : le binding Python
RUN pip install --no-cache-dir libvirt-python

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000
CMD ["python", "app.py"]
