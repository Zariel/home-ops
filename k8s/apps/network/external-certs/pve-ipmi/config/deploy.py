import argparse
import base64
import hashlib
import http.client
import os
from pathlib import Path
import re
import socket
import ssl
import sys
import time
import uuid
from http.cookies import SimpleCookie
from urllib.parse import urlencode
from xml.etree import ElementTree


HOST = os.environ.get("BMC_HOST", "pve-ipmi.cbannister.casa")
ADDRESS = os.environ.get("BMC_ADDRESS", "10.1.1.30")
SSL_PAGE = "/cgi/url_redirect.cgi?url_name=config_ssl"


def fingerprint(der):
    return hashlib.sha256(der).hexdigest()


class BMC:
    def __init__(self):
        self.cookies = {"langSetFlag": "0", "language": "English"}
        self.csrf = None
        self.pin = os.environ["BMC_BOOTSTRAP_SHA256"].lower().replace(":", "")
        if not re.fullmatch(r"[0-9a-f]{64}", self.pin):
            raise RuntimeError("Invalid bootstrap certificate fingerprint")

    def connect(self, verify=True):
        context = ssl.create_default_context() if verify else ssl._create_unverified_context()
        connection = http.client.HTTPSConnection(HOST, timeout=20, context=context)
        raw = socket.create_connection((ADDRESS, 443), timeout=20)
        try:
            connection.sock = context.wrap_socket(raw, server_hostname=HOST)
        except BaseException:
            raw.close()
            raise
        return connection

    def authenticated_connection(self):
        try:
            return self.connect()
        except ssl.SSLCertVerificationError:
            connection = self.connect(verify=False)
            if fingerprint(connection.sock.getpeercert(binary_form=True)) != self.pin:
                connection.close()
                raise RuntimeError("BMC TLS verification failed and bootstrap fingerprint differs")
            return connection

    def served_fingerprint(self):
        connection = self.authenticated_connection()
        try:
            return fingerprint(connection.sock.getpeercert(binary_form=True))
        finally:
            connection.close()

    def request(self, method, path, body=None, content_type=None):
        connection = self.authenticated_connection()
        headers = {"Cookie": "; ".join(k + "=" + v for k, v in self.cookies.items()),
                   "Origin": "https://" + HOST, "Referer": "https://" + HOST + SSL_PAGE}
        if self.csrf:
            headers["CSRF_TOKEN"] = self.csrf
        if content_type:
            headers["Content-Type"] = content_type
        try:
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            for name, value in response.getheaders():
                if name.lower() == "set-cookie":
                    parsed = SimpleCookie()
                    parsed.load(value)
                    self.cookies.update({k: v.value for k, v in parsed.items()})
            data = response.read()
            if response.status != 200:
                raise RuntimeError(f"BMC {method} {path} returned HTTP {response.status}")
            return data
        finally:
            connection.close()

    def form(self, path, data):
        return self.request("POST", path, urlencode(data), "application/x-www-form-urlencoded")

    def login(self):
        directory = Path(os.environ.get("CREDENTIALS_DIR", "/credentials"))
        user = (directory / "username").read_text().strip()
        password = (directory / "password").read_text()
        result = self.form("/cgi/login.cgi", {
            "name": base64.b64encode(user.encode()).decode(),
            "pwd": base64.b64encode(password.encode()).decode(), "check": "00"})
        if b"/cgi/url_redirect.cgi?url_name=mainmenu" not in result:
            raise RuntimeError("BMC login failed")
        page = self.request("GET", SSL_PAGE).decode()
        match = re.search(r'SmcCsrfInsert\s*\("CSRF_TOKEN",\s*"([^"]+)"\)', page)
        if not match:
            raise RuntimeError("BMC SSL page has no CSRF token")
        self.csrf = match.group(1)

    def ssl_status(self, operation):
        response = self.form("/cgi/ipmi.cgi", {"op": operation, "r": "(0,0)", "_": ""})
        return ElementTree.fromstring(response)

    def upload(self, cert, key):
        boundary = "ipmi-" + uuid.uuid4().hex
        parts = []
        for field, filename, value in [("cert_file", "fullchain.pem", cert),
                                       ("key_file", "privkey.pem", key)]:
            parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; '
                          f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
                         + value + b"\r\n")
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="CSRF_TOKEN"\r\n\r\n'
                      + self.csrf + f"\r\n--{boundary}--\r\n").encode())
        response = self.request("POST", "/cgi/upload_ssl.cgi", b"".join(parts),
                                "multipart/form-data; boundary=" + boundary)
        if b"CONFPAGE_RESET" not in response:
            raise RuntimeError("BMC did not acknowledge the certificate upload")
        info = self.ssl_status("SSL_VALIDATE.XML").find(".//SSL_INFO")
        if info is None or int(info.get("VALIDATE", "0")) != 1:
            raise RuntimeError("BMC rejected the uploaded certificate or key; reset skipped")

    def wait_for_certificate(self, desired, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                if self.served_fingerprint() == desired:
                    return True
            except (OSError, http.client.HTTPException, RuntimeError):
                pass
            time.sleep(3)
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Check login and SSL status without changing the BMC")
    args = parser.parse_args()
    bmc = BMC()
    if args.check:
        try:
            bmc.login()
            status = bmc.ssl_status("SSL_STATUS.XML").find(".//STATUS")
            if status is None:
                raise RuntimeError("BMC SSL status is missing")
            print("BMC login and SSL interface verified; certificate present:", status.get("CERT_EXIST"))
        finally:
            bmc.request("GET", "/cgi/logout.cgi")
        return

    directory = Path(os.environ.get("TLS_DIR", "/tls"))
    cert_path, key_path = directory / "tls.crt", directory / "tls.key"
    cert, key = cert_path.read_bytes(), key_path.read_bytes()
    # Python's bundled decoder reads certificate dates and SANs without an extra dependency.
    decoded = ssl._ssl._test_decode_cert(str(cert_path))
    if HOST not in [value for kind, value in decoded.get("subjectAltName", ()) if kind == "DNS"]:
        raise RuntimeError("Desired certificate does not cover the BMC hostname")
    if not ssl.cert_time_to_seconds(decoded["notBefore"]) <= time.time() < ssl.cert_time_to_seconds(decoded["notAfter"]):
        raise RuntimeError("Desired certificate is outside its validity period")
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert_path, key_path)
    leaf = re.search(rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", cert, re.S)
    desired = fingerprint(ssl.PEM_cert_to_DER_cert(leaf.group().decode()))
    if bmc.served_fingerprint() == desired:
        print("BMC already serves the desired certificate:", desired)
        return
    try:
        bmc.login()
        bmc.upload(cert, key)
        print("Certificate uploaded and validated by BMC")
        if not bmc.wait_for_certificate(desired, 21):
            print("Restarting BMC to activate certificate; host power is unchanged")
            try:
                bmc.form("/cgi/op.cgi", {"op": "main_bmcreset", "_": ""})
            except (OSError, http.client.RemoteDisconnected):
                # The reset may close the connection before returning its response.
                pass
            if not bmc.wait_for_certificate(desired, 150):
                raise RuntimeError("BMC is not serving the desired certificate after reset")
        print("BMC serves the desired certificate:", desired)
    finally:
        try:
            bmc.request("GET", "/cgi/logout.cgi")
        except (OSError, http.client.HTTPException, RuntimeError):
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Certificate deployment failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
