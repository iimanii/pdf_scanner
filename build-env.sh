#!/bin/bash

# Check if API key provided
if [ -z "$1" ]; then
    echo "Usage: $0 <virustotal-api-key>"
    exit 1
fi

API_KEY="$1"

# Validate API key length
if [ ${#API_KEY} -ne 64 ]; then
    echo "❌ Invalid API key length (${#API_KEY} chars, should be 64)"
    exit 1
fi

# Generate password and create .env file
DB_PASSWORD=$(openssl rand -hex 16 | tr -d '\n')

cat > .env << EOF
POSTGRES_DB=pdf_scanner
POSTGRES_USER=scanner_user
POSTGRES_PASSWORD=${DB_PASSWORD}
VIRUSTOTAL_API_KEY=${API_KEY}
EOF

chmod 600 .env
echo "✅ Configuration ready!"
echo "Next: docker-compose up --build"