import argparse
import hashlib
from html import unescape
from html.parser import HTMLParser
import http.client
from http.cookies import SimpleCookie
import os
from pathlib import Path
import re
import socket
import ssl
import sys
import time
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
import uuid


HOST = os.environ.get("PRINTER_HOST", "printer.cbannister.casa")
ADDRESS = os.environ.get("PRINTER_ADDRESS", "10.1.2.70")
CERTIFICATES = "/net/security/certificate/certificate.html"
IMPORT = "/net/security/certificate/import.html"
HTTP_SETTINGS = "/net/net/certificate/http.html"
IDLE = {"Ready", "Sleep", "Deep Sleep"}


def words(value):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", value)).split())


class Page(HTMLParser):
    def __init__(self, body):
        super().__init__()
        self.forms, self.links, self.lcd = [], [], []
        self.form = self.select = self.option = None
        self.monitoring = False
        self.text = body.decode("utf8", "replace")
        self.feed(self.text)

    def handle_starttag(self, tag, attributes):
        field = dict(attributes)
        if tag == "form":
            self.form = dict(field, controls=[])
            self.forms.append(self.form)
        elif tag == "input":
            if field.get("name") == "monitor_start":
                self.monitoring = True
            elif field.get("name") == "monitor_end":
                self.monitoring = False
            if self.form is not None:
                self.form["controls"].append(dict(field, tag=tag))
        elif tag == "select" and self.form is not None:
            self.select = dict(field, tag=tag, options=[])
            self.form["controls"].append(self.select)
        elif tag == "option" and self.select is not None:
            self.option = dict(field, text="")
            self.select["options"].append(self.option)
        elif tag == "a" and "href" in field:
            self.links.append(field["href"])

    def handle_endtag(self, tag):
        if tag == "form":
            self.form = None
        elif tag == "select":
            self.select = None
        elif tag == "option":
            self.option = None

    def handle_data(self, value):
        if self.option is not None:
            self.option["text"] += value
        if self.monitoring:
            self.lcd.append(value)

    def named_form(self, name):
        forms = [form for form in self.forms if form.get("id") == name]
        if len(forms) != 1:
            raise RuntimeError(f"Expected printer form {name} was not found")
        return forms[0]


def values(form, overrides=None):
    overrides = overrides or {}
    result = []
    for field in form["controls"]:
        name, kind = field.get("name"), field.get("type", "text")
        if not name or "disabled" in field:
            continue
        if field["tag"] == "select":
            selected = next((option for option in field["options"] if "selected" in option), field["options"][0])
            result.append((name, overrides.get(name, selected["value"])))
        elif kind in {"checkbox", "radio"}:
            if "checked" in field:
                result.append((name, field.get("value", "on")))
        elif kind not in {"file", "button", "submit", "reset"}:
            result.append((name, overrides.get(name, field.get("value", ""))))
    return result


def check_response(body, operation):
    text = words(body.decode("utf8", "replace"))
    if "Submit Error" in text or "Your request was rejected" in text:
        raise RuntimeError("Printer rejected " + operation)


class Printer:
    def __init__(self):
        self.pin = os.environ["PRINTER_BOOTSTRAP_SHA256"].lower().replace(":", "")
        if not re.fullmatch(r"[0-9a-f]{64}", self.pin):
            raise RuntimeError("Invalid printer bootstrap fingerprint")
        self.password = (Path(os.environ.get("CREDENTIALS_DIR", "/credentials")) / "password").read_text()
        if not self.password:
            raise RuntimeError("Printer password is empty")
        self.cookies = {}

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
            return self.connect(), True
        except ssl.SSLCertVerificationError:
            connection = self.connect(verify=False)
            actual = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
            if actual != self.pin:
                connection.close()
                raise RuntimeError("Printer TLS verification failed and bootstrap fingerprint differs")
            return connection, False

    def served_certificate(self):
        connection, verified = self.trusted_connection()
        try:
            return hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest(), verified
        finally:
            connection.close()

    def request(self, method, path, body=None, content_type=None):
        connection, _ = self.trusted_connection()
        try:
            headers = {"User-Agent": "Mozilla/5.0", "Origin": "https://" + HOST,
                       "Referer": "https://" + HOST + path,
                       "Cookie": "; ".join(name + "=" + value for name, value in self.cookies.items())}
            if content_type:
                headers["Content-Type"] = content_type
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            for name, value in response.getheaders():
                if name.lower() == "set-cookie":
                    cookie = SimpleCookie(); cookie.load(value)
                    self.cookies.update({name: item.value for name, item in cookie.items()})
            data = response.read(1024 * 1024 + 1)
            allowed = {200, 301, 302} if method == "POST" and path == "/home/status.html" else {200}
            if response.status not in allowed or len(data) > 1024 * 1024:
                raise RuntimeError(f"Printer {method} {path} returned an unexpected response ({response.status})")
            return data
        finally:
            connection.close()

    def submit(self, form, path, overrides=None):
        action = urlsplit(urljoin("https://" + HOST + path, form.get("action", path)))
        if action.scheme != "https" or action.netloc != HOST or action.path != path:
            raise RuntimeError("Printer form points outside the expected management page")
        fields = values(form, overrides)
        if not dict(fields).get("CSRFToken"):
            raise RuntimeError("Printer form has no CSRF token")
        body = self.request("POST", path, urlencode(fields).encode(), "application/x-www-form-urlencoded")
        check_response(body, "form submission")
        return body

    def login(self):
        self.cookies = {}
        page = Page(self.request("GET", "/home/status.html"))
        forms = [form for form in page.forms if any(field.get("type") == "password" for field in form["controls"])]
        if len(forms) != 1:
            raise RuntimeError("Expected printer login form was not found")
        form = forms[0]
        password_name = next(field["name"] for field in form["controls"] if field.get("type") == "password")
        # Login is the only form on this firmware without a CSRF token.
        action = urlsplit(urljoin("https://" + HOST + "/home/status.html", form.get("action", "")))
        if action.scheme != "https" or action.netloc != HOST or action.path != "/home/status.html":
            raise RuntimeError("Unexpected printer login action")
        self.request("POST", action.path, urlencode(values(form, {password_name: self.password})).encode(), "application/x-www-form-urlencoded")
        if not self.cookies.get("AuthCookie"):
            raise RuntimeError("Printer login failed; no further password attempts made")

    def status(self):
        page = Page(self.request("GET", "/home/monitor.html"))
        status = " ".join(" ".join(page.lcd).split())
        if not status:
            raise RuntimeError("Could not read printer LCD status")
        return status

    def http_settings(self):
        form = Page(self.request("GET", HTTP_SETTINGS)).named_form("http_setting")
        selectors = [field for field in form["controls"] if field["tag"] == "select"]
        if len(selectors) != 1:
            raise RuntimeError("Could not identify the printer TLS certificate selector")
        selected = next((option for option in selectors[0]["options"] if "selected" in option), selectors[0]["options"][0])
        checkboxes = {field["name"]: "checked" in field for field in form["controls"] if field.get("type") == "checkbox"}
        return form, selectors[0], selected["value"], checkboxes

    def certificates(self):
        page = Page(self.request("GET", CERTIFICATES))
        if any(urlsplit(link).path.endswith("/install.html") or urlsplit(link).path == "install.html" for link in page.links):
            raise RuntimeError("Printer has a pending CSR; refusing to replace another certificate operation")
        ids, deletable = set(), set()
        for link in page.links:
            url = urlsplit(link)
            index = parse_qs(url.query).get("idx", [""])[0]
            if index.isdigit():
                if url.path.endswith("view.html"):
                    ids.add(index)
                elif url.path.endswith("delete.html"):
                    deletable.add(index)
        result = {}
        for index in sorted(ids):
            body = self.request("GET", "/net/security/certificate/view.html?idx=" + index).decode("utf8", "replace")
            pairs = {words(key): words(value) for key, value in re.findall(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", body, re.S)}
            serial = pairs.get("Serial Number", "").replace(":", "").strip()
            subject = re.search(r"\bCN\s*:\s*(\S+)", pairs.get("Subject", ""))
            if not re.fullmatch(r"[0-9a-fA-F]+", serial):
                raise RuntimeError("Could not identify a stored printer certificate")
            result[index] = {"serial": int(serial, 16), "subject": subject.group(1) if subject else "",
                             "issuer": pairs.get("Issuer", ""), "deletable": index in deletable}
        return result

    def cleanup(self, active):
        # Retire only unused Let's Encrypt certificates for this managed hostname.
        for index, cert in self.certificates().items():
            if index == active or not cert["deletable"] or cert["subject"] != HOST or "Let's Encrypt" not in cert["issuer"]:
                continue
            path = "/net/security/certificate/delete.html"
            form = Page(self.request("GET", path + "?idx=" + index)).named_form("cert_delete")
            if dict(values(form)).get("hidden_certificate_idx") != index:
                raise RuntimeError("Printer certificate delete confirmation differs from the requested slot")
            self.submit(form, path)
            print("Retired previous managed certificate slot:", index)

    def upload(self, bundle, serial):
        form = Page(self.request("GET", IMPORT)).named_form("cert_import")
        controls = form["controls"]
        passwords = [field for field in controls if field.get("type") == "password"]
        if len(passwords) != 1 or sum(field.get("type") == "file" for field in controls) != 1:
            raise RuntimeError("Unexpected printer certificate import form")
        if len(self.password) > int(passwords[0].get("maxlength", "51")):
            raise RuntimeError("PKCS12 password exceeds the printer import limit")
        if not dict(values(form)).get("CSRFToken"):
            raise RuntimeError("Certificate import form has no CSRF token")
        boundary = "printer-" + uuid.uuid4().hex
        parts = []
        # The Brother multipart parser requires controls in browser/DOM order.
        for field in controls:
            name, kind = field.get("name"), field.get("type")
            if not name or kind in {"submit", "button", "reset"}:
                continue
            if kind == "file":
                parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="certkey.p12"\r\nContent-Type: application/octet-stream\r\n\r\n').encode() + bundle + b"\r\n")
            else:
                value = self.password if kind == "password" or name == "hidden_cert_import_password" else field.get("value", "")
                parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode())
        parts.append(f"--{boundary}--\r\n".encode())
        body = self.request("POST", IMPORT, b"".join(parts), "multipart/form-data; boundary=" + boundary)
        check_response(body, "certificate import")
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            for index, cert in self.certificates().items():
                if cert["serial"] == serial and cert["subject"] == HOST:
                    return index
            time.sleep(3)
        raise RuntimeError("Uploaded certificate did not appear in the printer certificate store")

    def activate(self, index, desired):
        script = self.request("GET", "/common/js/restart_flag.js").decode()
        flag = re.search(r"form\.(\w+)\.value\s*=\s*flg", script)
        form, selector, _, preferences = self.http_settings()
        if not flag or flag.group(1) not in dict(values(form)):
            raise RuntimeError("Could not identify the printer restart flag")
        if index not in [option["value"] for option in selector["options"]]:
            raise RuntimeError("Imported certificate is not offered by the printer TLS selector")
        body = self.submit(form, HTTP_SETTINGS, {selector["name"]: index, flag.group(1): "1"})
        page = Page(body)
        forms = [form for form in page.forms if "http_page_mode" in dict(values(form))]
        if len(forms) != 1 or "restart" not in words(page.text).lower():
            raise RuntimeError("Printer did not present the expected restart confirmation")
        confirmation = forms[0]
        if any(field["tag"] == "select" or field.get("type") in {"checkbox", "radio"} for field in confirmation["controls"]):
            raise RuntimeError("Unexpected protocol changes in the printer restart confirmation")
        if dict(values(confirmation))["http_page_mode"] not in {"4", "5"}:
            raise RuntimeError("Unknown printer restart confirmation mode")
        status = self.status()
        if status not in IDLE:
            print("Printer is busy; activation deferred until the next scheduled check:", status)
            return False
        print("Activating the managed certificate; printer status:", status)
        try:
            self.submit(confirmation, HTTP_SETTINGS)
        except (OSError, http.client.RemoteDisconnected):
            # A printer restart may close HTTPS before returning its response.
            pass
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                fingerprint, verified = self.served_certificate()
                if verified and fingerprint == desired:
                    break
            except (OSError, http.client.HTTPException, RuntimeError):
                pass
            time.sleep(3)
        else:
            raise RuntimeError("Printer did not start serving the desired publicly trusted certificate")
        self.login()
        _, _, active, after = self.http_settings()
        if active != index or after != preferences:
            raise RuntimeError("Printer TLS selection or printing protocol preferences differ after activation")
        self.cleanup(active)
        print("Printer serves the desired certificate; printing protocol preferences preserved:", desired)
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Check printer access without changing settings")
    args = parser.parse_args()
    printer = Printer()
    if args.check:
        printer.login()
        print("Printer certificate controls accessible; LCD status:", printer.status())
        print("Stored certificate slots:", len(printer.certificates()))
        printer.http_settings()
        return
    directory = Path(os.environ.get("TLS_DIR", "/tls"))
    cert_path, key_path = directory / "tls.crt", directory / "tls.key"
    cert = ssl._ssl._test_decode_cert(str(cert_path))
    if HOST not in [value for kind, value in cert.get("subjectAltName", ()) if kind == "DNS"]:
        raise RuntimeError("Desired certificate does not cover the printer hostname")
    if not ssl.cert_time_to_seconds(cert["notBefore"]) <= time.time() < ssl.cert_time_to_seconds(cert["notAfter"]):
        raise RuntimeError("Desired certificate is outside its validity period")
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert_path, key_path)
    pem = re.search(rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", cert_path.read_bytes(), re.S).group().decode()
    desired = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
    current, verified = printer.served_certificate()
    if current == desired:
        if not verified:
            raise RuntimeError("Desired printer certificate is served but its public CA chain could not be verified")
        print("Printer already serves the desired certificate:", desired)
        return
    printer.login()
    status = printer.status()
    if status not in IDLE:
        print("Printer is busy; certificate renewal deferred until the next scheduled check:", status)
        return
    stored = printer.certificates()
    _, _, active, _ = printer.http_settings()
    serial = int(cert["serialNumber"], 16)
    matches = [index for index, saved in stored.items() if saved["serial"] == serial and saved["subject"] == HOST]
    if len(matches) > 1:
        raise RuntimeError("Multiple printer slots match the desired certificate")
    if matches:
        index = matches[0]
    else:
        if len(stored) >= 6:
            printer.cleanup(active)
            if len(printer.certificates()) >= 6:
                raise RuntimeError("Printer certificate store is full; unrelated certificates were preserved")
        index = printer.upload((directory / "keystore.p12").read_bytes(), serial)
    printer.activate(index, desired)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Printer certificate deployment failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
