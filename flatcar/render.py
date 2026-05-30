#!/usr/bin/env python3
import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FLATCAR_DIR = ROOT / "flatcar"
CONFIG_FILE = Path(os.environ.get("FLATCAR_CONFIG") or FLATCAR_DIR / "config.pkl")
TEMPLATE_DIR = FLATCAR_DIR / "templates"
OUT = ROOT / "artifacts" / "flatcar"
MATCHBOX_OUT = OUT / "matchbox"
MATCHBOX_HTTP_BASE = os.environ.get("MATCHBOX_HTTP_BASE", "http://10.5.0.8")
COMPONENTS = ["ssh", "host", "updates", "containerd", "kubernetes", "bird"]


def set_output(path):
    global OUT, MATCHBOX_OUT

    OUT = path
    MATCHBOX_OUT = OUT / "matchbox"


def run(args, *, input_data=None, stdout=None, stderr=None):
    return subprocess.run(args, check=True, input=input_data, stdout=stdout, stderr=stderr)


def capture(args, *, input_data=None, stderr=None):
    return run(args, input_data=input_data, stdout=subprocess.PIPE, stderr=stderr).stdout


def need(command):
    if shutil.which(command) is None:
        raise SystemExit(f"missing required command: {command}")


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def validate_json(path):
    with path.open() as f:
        json.load(f)


def validate_yaml(path):
    run(["yq", ".", str(path)], stdout=subprocess.DEVNULL)


def read_pkl(path):
    return json.loads(capture(["pkl", "eval", "--format", "json", str(path)]))


def render_template(template, data, output, tmpdir):
    data_file = tmpdir / f"{output.name}.json"
    write_json(data_file, data)
    run(
        [
            "minijinja-cli",
            "--strict",
            "--autoescape",
            "none",
            "--safe-path",
            str(TEMPLATE_DIR),
            str(TEMPLATE_DIR / template),
            str(data_file),
            "--output",
            str(output),
        ]
    )


def transpile_butane(source, output):
    with output.open("wb") as f:
        run(["butane", "--strict", str(source)], stdout=f)
    validate_json(output)


def merge_butane(sources, output):
    with output.open("wb") as f:
        run(
            ["yq", "eval-all", ". as $item ireduce ({}; . *+ $item)", *[str(source) for source in sources]],
            stdout=f,
        )
    validate_yaml(output)


def read_op(path):
    return capture(["op", "read", path]).decode().rstrip("\n")


def check_secrets(tmpdir):
    ca_key = tmpdir / "check-ca.key"
    ca_crt = tmpdir / "check-ca.crt"
    run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_crt),
            "-days",
            "1",
            "-subj",
            "/CN=flatcar-render-check",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {
        "kubeadm_token": "abcdef.0123456789abcdef",
        "kubeadm_certificate_key": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "kubeadm_ca_crt": ca_crt.read_text(),
        "kubeadm_ca_key": ca_key.read_text(),
        "ssh_public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeFlatcarRenderCheckOnly flatcar-render-check",
    }


def op_secrets():
    item = "op://Kubernetes/flatcar-kubeadm-hollywoo"
    return {
        "kubeadm_token": read_op(f"{item}/kubeadm-token"),
        "kubeadm_certificate_key": read_op(f"{item}/kubeadm-certificate-key"),
        "kubeadm_ca_crt": read_op(f"{item}/kubernetes-ca-crt"),
        "kubeadm_ca_key": read_op(f"{item}/kubernetes-ca-key"),
        "ssh_public_key": read_op(f"{item}/ssh-public-key"),
    }


def ca_hash(ca_crt, tmpdir):
    ca_file = tmpdir / "ca.crt"
    ca_file.write_text(ca_crt)
    pubkey = capture(["openssl", "x509", "-pubkey", "-in", str(ca_file)])
    der = capture(
        ["openssl", "rsa", "-pubin", "-outform", "der"],
        input_data=pubkey,
        stderr=subprocess.DEVNULL,
    )
    digest = capture(["openssl", "dgst", "-sha256", "-hex"], input_data=der)
    return digest.decode().strip().split()[-1]


def render_inline_template(name, text, data, tmpdir):
    if "{{" not in text and "{%" not in text:
        return text

    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", name)
    template = tmpdir / f"{stem}.j2"
    data_file = tmpdir / f"{stem}.json"
    output = tmpdir / f"{stem}.out"
    template.write_text(text)
    write_json(data_file, data)
    run(
        [
            "minijinja-cli",
            "--strict",
            "--autoescape",
            "none",
            str(template),
            str(data_file),
            "--output",
            str(output),
        ]
    )
    return output.read_text()


def render_networkd_value(value):
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def networkd_file_contents(networkd_file):
    if networkd_file.get("contents") is not None:
        return str(networkd_file["contents"]).rstrip("\n") + "\n"

    lines = []
    for section in networkd_file.get("sections", []):
        lines.append(f"[{section['name']}]")
        for key, value in section.get("settings", {}).items():
            values = value if isinstance(value, list) else [value]
            for item in values:
                lines.append(f"{key}={render_networkd_value(item)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_networkd_files(node, data, tmpdir):
    rendered = []
    for index, networkd_file in enumerate(node.get("_networkd_files", [])):
        name = render_inline_template(
            f"{node['hostname']}-networkd-{index}-name",
            networkd_file["name"],
            data,
            tmpdir,
        )
        contents = render_inline_template(
            f"{node['hostname']}-networkd-{index}-contents",
            networkd_file_contents(networkd_file),
            data,
            tmpdir,
        )
        rendered.append(
            {
                "name": name,
                "mode": networkd_file.get("mode", "0644"),
                "contents": contents.rstrip("\n"),
                "contents_indented": "\n".join(
                    f"          {line}" if line else "" for line in contents.rstrip("\n").split("\n")
                ),
            }
        )

    return rendered


def list_value(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def merge_wait_online(current, override):
    for key, value in override.items():
        if key in {"networkd", "kubelet"}:
            current[key] = [str(item) for item in list_value(value)]
        else:
            current[key] = copy.deepcopy(value)


def add_networkd_files(files_by_name, files, source, *, replace):
    for networkd_file in files:
        name = networkd_file.get("name")
        if not name:
            raise SystemExit(f"{source} has a networkd file without a name")
        if name in files_by_name and not replace:
            raise SystemExit(f"duplicate networkd file {name!r} from {source}")
        files_by_name[name] = copy.deepcopy(networkd_file)


def role_lookup(config):
    roles = {}
    for role in config.get("roles", []):
        name = role.get("name")
        if not name:
            raise SystemExit("role is missing name")
        if name in roles:
            raise SystemExit(f"duplicate role: {name}")
        roles[name] = role
    return roles


def apply_node_roles(raw_node, roles):
    node = copy.deepcopy(raw_node)
    files_by_name = {}
    wait_online = {
        "networkd": [],
        "kubelet": [],
        "kubelet_timeout": 30,
    }

    for role_name in list_value(node.get("roles", [])):
        role = roles.get(role_name)
        if role is None:
            raise SystemExit(f"node {node.get('hostname')} references unknown role: {role_name}")
        merge_wait_online(wait_online, role.get("wait_online", {}))
        add_networkd_files(
            files_by_name,
            role.get("networkd", {}).get("files", []),
            f"role {role_name}",
            replace=False,
        )

    merge_wait_online(wait_online, node.get("wait_online", {}))
    add_networkd_files(
        files_by_name,
        node.get("networkd", {}).get("files", []),
        f"node {node.get('hostname')}",
        replace=True,
    )

    node["wait_online"] = wait_online
    node["_networkd_files"] = list(files_by_name.values())
    return node


def load_config():
    config = read_pkl(CONFIG_FILE)

    bakery = {}
    for raw_item in config.get("bakery", []):
        item = dict(raw_item)
        name = item.get("name")
        version = item.get("version")
        arch = item.get("arch", "x86-64")
        item["arch"] = arch
        if name and version:
            item["sysext"] = f"{name}-{version}-{arch}.raw"
            item["minor"] = version.rsplit(".", 1)[0]
            bakery[name] = item

    roles = role_lookup(config)
    nodes = []
    for raw_node in config.get("nodes", []):
        node = apply_node_roles(raw_node, roles)
        extra_disks = [dict(disk) for disk in node.get("extra_disks", [])]
        node["extra_disks"] = [dict(disk) for disk in extra_disks]
        node["extra_disks_json"] = json.dumps(node["extra_disks"], sort_keys=True)
        nodes.append(node)

    return {
        "cluster": config.get("cluster", {}),
        "bakery": bakery,
        "nodes": nodes,
    }


def validate_no_templates():
    pattern = re.compile(r"\{\{\s|\s\}\}|\{%\s|\s%\}")
    matches = []
    for path in OUT.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                matches.append(f"{path}:{lineno}:{line}")
    if matches:
        print(f"unresolved template markers found in {OUT}", file=sys.stderr)
        print("\n".join(matches), file=sys.stderr)
        raise SystemExit(1)


def prepare_output():
    shutil.rmtree(OUT, ignore_errors=True)
    for path in [
        OUT / "butane" / "components",
        OUT / "butane" / "installers",
        OUT / "butane" / "nodes",
        OUT / "butane" / "secrets",
        OUT / "kubeadm",
        MATCHBOX_OUT / "groups",
        MATCHBOX_OUT / "ignition" / "components",
        MATCHBOX_OUT / "ignition" / "installers",
        MATCHBOX_OUT / "ignition" / "nodes",
        MATCHBOX_OUT / "profiles",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def render_static_components():
    for component in ["host", "updates", "bird"]:
        source = FLATCAR_DIR / "butane" / "components" / f"{component}.bu"
        rendered = OUT / "butane" / "components" / f"{component}.bu"
        validate_yaml(source)
        shutil.copy2(source, rendered)
        transpile_butane(source, MATCHBOX_OUT / "ignition" / "components" / f"{component}.ign")


def render_component_templates(data, tmpdir):
    for template in sorted((TEMPLATE_DIR / "butane" / "components").glob("*.bu.j2")):
        name = template.name.removesuffix(".bu.j2")
        rendered = OUT / "butane" / "components" / f"{name}.bu"
        ignition = MATCHBOX_OUT / "ignition" / "components" / f"{name}.ign"
        render_template(str(template.relative_to(TEMPLATE_DIR)), data, rendered, tmpdir)
        validate_yaml(rendered)
        transpile_butane(rendered, ignition)


def render_node(node, config, secrets, tmpdir):
    host = node["hostname"]
    data = {
        "node": node,
        "cluster": config["cluster"],
        "bakery": config["bakery"],
        "secrets": secrets,
        "matchbox_http_base": MATCHBOX_HTTP_BASE,
    }
    node["networkd_files"] = render_networkd_files(node, data, tmpdir)

    (OUT / "butane" / "secrets" / host).mkdir(parents=True, exist_ok=True)

    kubeadm_template = "kubeadm/init.yaml.j2" if node.get("bootstrap") else "kubeadm/join.yaml.j2"
    kubeadm_output = OUT / "kubeadm" / f"{host}.yaml"
    render_template(kubeadm_template, data, kubeadm_output, tmpdir)
    validate_yaml(kubeadm_output)

    kubeadm_data = dict(data)
    kubeadm_data["kubeadm_config"] = kubeadm_output.read_text()
    kubeadm_bu = OUT / "butane" / "secrets" / host / "kubeadm.bu"
    render_template("butane/secrets/kubeadm.bu.j2", kubeadm_data, kubeadm_bu, tmpdir)
    validate_yaml(kubeadm_bu)

    node_root = OUT / "butane" / "nodes" / f"{host}-root.bu"
    render_template("butane/nodes/node.bu.j2", data, node_root, tmpdir)
    validate_yaml(node_root)

    installer_root = OUT / "butane" / "installers" / f"{host}-root.bu"
    render_template("butane/installers/installer.bu.j2", data, installer_root, tmpdir)
    validate_yaml(installer_root)

    node_bu = OUT / "butane" / "nodes" / f"{host}.bu"
    node_sources = [
        *[OUT / "butane" / "components" / f"{component}.bu" for component in COMPONENTS],
        kubeadm_bu,
        node_root,
    ]
    merge_butane(node_sources, node_bu)
    transpile_butane(node_bu, MATCHBOX_OUT / "ignition" / "nodes" / f"{host}.ign")

    installer_bu = OUT / "butane" / "installers" / f"{host}.bu"
    merge_butane([OUT / "butane" / "components" / "ssh.bu", installer_root], installer_bu)
    transpile_butane(installer_bu, MATCHBOX_OUT / "ignition" / "installers" / f"{host}.ign")

    for template, output in [
        ("matchbox/profiles/profile-node.json.j2", f"{host}-node.json"),
        ("matchbox/profiles/profile-installer.json.j2", f"{host}-installer.json"),
        ("matchbox/groups/group-node.json.j2", f"{host}.json"),
        ("matchbox/groups/group-installer.json.j2", f"{host}-installer.json"),
    ]:
        base = MATCHBOX_OUT / "profiles" if template.startswith("matchbox/profiles/") else MATCHBOX_OUT / "groups"
        path = base / output
        render_template(template, data, path, tmpdir)
        validate_json(path)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Render Flatcar Butane, Ignition, kubeadm, and matchbox artifacts."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="use local throwaway values instead of reading kubeadm and SSH material from 1Password",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    for command in ["pkl", "yq", "openssl", "minijinja-cli", "butane"]:
        need(command)
    if not args.check:
        need("op")

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        if args.check:
            set_output(tmpdir / "flatcar-render-check")

        config = load_config()
        secrets = check_secrets(tmpdir) if args.check else op_secrets()
        secrets["kubeadm_ca_hash"] = ca_hash(secrets["kubeadm_ca_crt"], tmpdir)

        prepare_output()
        render_static_components()
        component_data = {"cluster": config["cluster"], "bakery": config["bakery"], "secrets": secrets}
        render_component_templates(component_data, tmpdir)
        for node in config["nodes"]:
            render_node(node, config, secrets, tmpdir)

        validate_no_templates()
        if args.check:
            print("Flatcar render check passed")
        else:
            print(f"Rendered Flatcar artifacts in {OUT}")


if __name__ == "__main__":
    main()
