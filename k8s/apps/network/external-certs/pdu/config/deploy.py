import argparse
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import ssl
import sys
import time
import uuid


HOST = os.environ.get("PDU_HOST", "pdu.cbannister.casa")
ADDRESS = os.environ.get("PDU_ADDRESS", "10.1.0.31")


def fingerprint(pem):
    leaf = re.search(rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", pem, re.S)
    if leaf is None:
        raise RuntimeError("Certificate response contains no PEM certificate")
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(leaf.group().decode())).hexdigest()


class PDU:
    def __init__(self):
        self.pin = os.environ["PDU_BOOTSTRAP_SHA256"].lower().replace(":", "")
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

    def trusted_connection(self):
        try:
            return self.connect()
        except ssl.SSLCertVerificationError:
            connection = self.connect(verify=False)
            actual = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
            if actual != self.pin:
                connection.close()
                raise RuntimeError("PDU TLS verification failed and bootstrap fingerprint differs")
            return connection

    def served_fingerprint(self):
        connection = self.trusted_connection()
        try:
            return hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
        finally:
            connection.close()

    def request(self, method, path, body=None, content_type=None):
        connection = self.trusted_connection()
        try:
            directory = Path(os.environ.get("CREDENTIALS_DIR", "/credentials"))
            user = (directory / "username").read_text().strip()
            password = (directory / "password").read_text()
            auth = base64.b64encode((user + ":" + password).encode()).decode()
            headers = {"Authorization": "Basic " + auth}
            if content_type:
                headers["Content-Type"] = content_type
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            data = response.read()
            if response.status != 200:
                raise RuntimeError(f"PDU {method} {path} returned HTTP {response.status}")
            return data
        finally:
            connection.close()

    def rpc(self, method):
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": {}})
        data = json.loads(self.request("POST", "/server_ssl_cert", payload, "application/json"))
        if data.get("error"):
            raise RuntimeError(f"PDU certificate method {method} failed, code {data['error'].get('code')}")
        if not isinstance(data.get("result"), dict):
            raise RuntimeError("PDU certificate API returned an unexpected response")
        return data["result"]

    def pending_fingerprint(self):
        return fingerprint(self.request("GET", "/cgi-bin/server_ssl_cert_download.cgi?tag=new_cert"))

    def upload(self, cert, key):
        boundary = "certificate-" + uuid.uuid4().hex
        parts = []
        for name, filename, value in [("cert_file", "fullchain.crt", cert), ("key_file", "private.key", key)]:
            parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                          f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
                         + value + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        response = self.request("POST", "/cgi-bin/server_ssl_cert_upload.cgi", b"".join(parts),
                                "multipart/form-data; boundary=" + boundary)
        if response.strip() != b"return_code=0":
            raise RuntimeError("PDU rejected the certificate upload")

    def deploy(self, cert, key, desired):
        info = self.rpc("getInfo")["info"]
        if info.get("havePendingReq"):
            raise RuntimeError("PDU has a pending CSR; refusing to replace another certificate operation")
        if info.get("havePendingCert"):
            if self.pending_fingerprint() != desired:
                raise RuntimeError("PDU has a different pending certificate; refusing to replace it")
        else:
            self.upload(cert, key)
        if self.pending_fingerprint() != desired:
            raise RuntimeError("PDU staged certificate differs from the desired certificate; activation skipped")
        try:
            if self.rpc("installPendingKeyPair").get("_ret_") != 0:
                raise RuntimeError("PDU rejected certificate activation")
        except (OSError, http.client.RemoteDisconnected):
            # HTTPS may restart before its activation response is returned.
            pass
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                if self.served_fingerprint() == desired:
                    print("PDU serves the desired certificate:", desired)
                    return
            except (OSError, http.client.HTTPException, RuntimeError):
                pass
            time.sleep(3)
        raise RuntimeError("PDU did not start serving the desired certificate")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Check certificate API access without changing the PDU")
    args = parser.parse_args()
    pdu = PDU()
    if args.check:
        info = pdu.rpc("getInfo")["info"]
        print("PDU certificate API accessible; pending CSR:", info["havePendingReq"],
              "pending certificate:", info["havePendingCert"])
        return
    directory = Path(os.environ.get("TLS_DIR", "/tls"))
    cert_path, key_path = directory / "tls.crt", directory / "tls.key"
    cert, key = cert_path.read_bytes(), key_path.read_bytes()
    decoded = ssl._ssl._test_decode_cert(str(cert_path))
    if HOST not in [value for kind, value in decoded.get("subjectAltName", ()) if kind == "DNS"]:
        raise RuntimeError("Desired certificate does not cover the PDU hostname")
    if not ssl.cert_time_to_seconds(decoded["notBefore"]) <= time.time() < ssl.cert_time_to_seconds(decoded["notAfter"]):
        raise RuntimeError("Desired certificate is outside its validity period")
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert_path, key_path)
    desired = fingerprint(cert)
    if pdu.served_fingerprint() == desired:
        print("PDU already serves the desired certificate:", desired)
        return
    pdu.deploy(cert, key, desired)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Certificate deployment failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
