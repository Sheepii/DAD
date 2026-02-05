import os
import sys
from pathlib import Path
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta

import manage


def _ensure_dev_cert(cert_path: Path, key_path: Path) -> None:
    if cert_path.exists() and key_path.exists():
        return
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        import ipaddress
    except Exception as exc:
        raise RuntimeError(
            "cryptography is required to generate HTTPS certificates. "
            "Install dependencies and try again."
        ) from exc

    cert_path.parent.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "DAD Local"),
            x509.NameAttribute(NameOID.COMMON_NAME, "DAD Local Dev"),
        ]
    )
    san_list = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        x509.IPAddress(ipaddress.ip_address("192.168.0.11")),
    ]

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow() - timedelta(days=1))
        .not_valid_after(datetime.utcnow() + timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
        .sign(key, hashes.SHA256())
    )

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def _start_redirect_server(http_port: int, https_port: int) -> None:
    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            host = self.headers.get("Host", "localhost")
            if ":" in host:
                host = host.split(":", 1)[0]
            location = f"https://{host}:{https_port}{self.path}"
            self.send_response(302)
            self.send_header("Location", location)
            self.end_headers()

        def log_message(self, format, *args):  # noqa: A002
            return

    server = HTTPServer(("0.0.0.0", http_port), RedirectHandler)
    server.serve_forever()


def main() -> None:
    manage.ensure_requirements()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dad.settings")

    from django.core.wsgi import get_wsgi_application
    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from wsgiref.simple_server import make_server

    host = "0.0.0.0"
    https_port = 8443
    http_port = 8000
    if len(sys.argv) > 1:
        host_port = sys.argv[1]
        if ":" in host_port:
            host, port_str = host_port.split(":", 1)
            https_port = int(port_str)
        else:
            https_port = int(host_port)

    cert_path = Path("certs") / "dev.crt"
    key_path = Path("certs") / "dev.key"
    _ensure_dev_cert(cert_path, key_path)

    app = StaticFilesHandler(get_wsgi_application())
    httpd = make_server(host, https_port, app)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    redirect_thread = threading.Thread(
        target=_start_redirect_server, args=(http_port, https_port), daemon=True
    )
    redirect_thread.start()

    print(f"Starting HTTPS server at https://{host}:{https_port}")
    print(f"Redirecting http://{host}:{http_port} -> https://{host}:{https_port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
