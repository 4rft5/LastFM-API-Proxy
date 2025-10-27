#!/bin/bash
set -e

if [ ! -f /app/certs/cert.pem ]; then
    echo "Generating self-signed certificate..."
    
    cat > /tmp/san.cnf <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
CN = ws.audioscrobbler.com

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = ws.audioscrobbler.com
DNS.2 = *.audioscrobbler.com
IP.1 = 127.0.0.1
EOF

    openssl req -x509 -newkey rsa:4096 \
        -keyout /app/certs/key.pem \
        -out /app/certs/cert.pem \
        -days 3650 -nodes \
        -subj "/CN=ws.audioscrobbler.com" \
        -extensions v3_req \
        -config /tmp/san.cnf
    
    chmod 644 /app/certs/cert.pem
    chmod 600 /app/certs/key.pem
    
    echo "Certificate generated successfully!"
    ls -la /app/certs/
else
    echo "Certificate already exists:"
    ls -la /app/certs/
fi

cp /app/certs/cert.pem /app/certs/lastfm-proxy.crt
echo "Certificate copied to /app/certs/lastfm-proxy.crt"

echo "Testing nginx configuration..."
nginx -t

echo "Starting supervisord..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf