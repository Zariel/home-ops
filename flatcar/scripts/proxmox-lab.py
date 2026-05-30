#!/usr/bin/env python3
import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_pkl(path):
    if shutil.which("pkl") is None:
        raise SystemExit("missing required command: pkl")
    return json.loads(subprocess.check_output(["pkl", "eval", "--format", "json", str(path)], text=True))


def load_config(path):
    config = read_pkl(path)

    proxmox = config.get("proxmox", {})
    if "host" not in proxmox:
        raise SystemExit(f"{path}: [proxmox].host is required")
    if "storage" not in proxmox:
        raise SystemExit(f"{path}: [proxmox].storage is required")
    if "bridge" not in proxmox:
        raise SystemExit(f"{path}: [proxmox].bridge is required")

    vms = config.get("vms", [])
    if not vms:
        raise SystemExit(f"{path}: at least one [[vms]] entry is required")

    vmid_base = int(proxmox.get("vmid_base", 9300))
    normalized = []
    for index, raw_vm in enumerate(vms):
        vm = dict(raw_vm)
        vm.setdefault("vmid", vmid_base + index)
        vm.setdefault("memory_mb", proxmox.get("memory_mb", 8192))
        vm.setdefault("cores", proxmox.get("cores", 4))
        vm.setdefault("cpu", proxmox.get("cpu", "host"))
        vm.setdefault("os_disk_gb", proxmox.get("os_disk_gb", 64))
        vm.setdefault("extra_disks_gb", proxmox.get("extra_disks_gb", []))
        vm.setdefault("start", proxmox.get("start", True))
        vm.setdefault("tags", proxmox.get("tags", ["flatcar-lab"]))

        if "name" not in vm:
            raise SystemExit(f"{path}: [[vms]] entry {index} is missing name")

        nics = [dict(nic) for nic in vm.get("nics", [])]
        if not nics:
            mac = vm.get("mac")
            if mac is None:
                raise SystemExit(f"{path}: {vm['name']} needs mac or [[vms.nics]]")
            nics = [{"mac": mac}]

        for nic in nics:
            nic.setdefault("bridge", proxmox["bridge"])
            nic.setdefault("model", proxmox.get("nic_model", "virtio"))
            if "mac" not in nic:
                raise SystemExit(f"{path}: {vm['name']} has a NIC without mac")

        vm["nics"] = nics
        normalized.append(vm)

    proxmox.setdefault("bios", "ovmf")
    proxmox.setdefault("machine", "q35")
    proxmox.setdefault("scsihw", "virtio-scsi-single")
    proxmox.setdefault("boot_order", "scsi0;net0")
    proxmox.setdefault("ostype", "l26")
    proxmox.setdefault("agent", True)
    proxmox.setdefault("onboot", False)

    return proxmox, normalized


def qm(host, args, *, dry_run, check=True):
    command = shlex.join(["qm", *[str(arg) for arg in args]])
    if dry_run:
        print(f"ssh {shlex.quote(host)} {shlex.quote(command)}")
        return ""

    result = subprocess.run(
        ["ssh", host, "sh", "-lc", command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise subprocess.CalledProcessError(result.returncode, command, result.stdout, result.stderr)
    return result.stdout


def vm_exists(host, vmid, *, dry_run):
    if dry_run:
        return False
    result = subprocess.run(
        ["ssh", host, "sh", "-lc", shlex.join(["qm", "status", str(vmid)])],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return result.returncode == 0


def vm_running(host, vmid, *, dry_run):
    if dry_run:
        return False
    output = qm(host, ["status", vmid], dry_run=False)
    return "status: running" in output


def disk_arg(storage, size_gb):
    return f"{storage}:{size_gb},discard=on,ssd=1"


def nic_arg(nic):
    return f"{nic['model']}={nic['mac']},bridge={nic['bridge']}"


def create_vm(proxmox, vm, *, dry_run):
    host = proxmox["host"]
    storage = proxmox["storage"]
    vmid = str(vm["vmid"])

    if vm_exists(host, vmid, dry_run=dry_run):
        raise SystemExit(f"VM {vmid} already exists; use recreate or destroy first")

    create_args = [
        "create",
        vmid,
        "--name",
        vm["name"],
        "--memory",
        vm["memory_mb"],
        "--cores",
        vm["cores"],
        "--cpu",
        vm["cpu"],
        "--ostype",
        proxmox["ostype"],
        "--machine",
        proxmox["machine"],
        "--bios",
        proxmox["bios"],
        "--scsihw",
        proxmox["scsihw"],
        "--boot",
        f"order={proxmox['boot_order']}",
        "--onboot",
        1 if proxmox["onboot"] else 0,
    ]
    if proxmox["agent"]:
        create_args.extend(["--agent", "enabled=1"])
    if vm["tags"]:
        create_args.extend(["--tags", ";".join(vm["tags"])])

    qm(host, create_args, dry_run=dry_run)

    set_args = ["set", vmid]
    for index, nic in enumerate(vm["nics"]):
        set_args.extend([f"--net{index}", nic_arg(nic)])
    set_args.extend(["--scsi0", disk_arg(storage, vm["os_disk_gb"])])
    for index, size_gb in enumerate(vm["extra_disks_gb"], start=1):
        set_args.extend([f"--scsi{index}", disk_arg(storage, size_gb)])
    set_args.extend(["--efidisk0", f"{storage}:0,efitype=4m,pre-enrolled-keys=0"])
    qm(host, set_args, dry_run=dry_run)

    if vm["start"]:
        qm(host, ["start", vmid], dry_run=dry_run)


def destroy_vm(proxmox, vm, *, dry_run):
    host = proxmox["host"]
    vmid = str(vm["vmid"])

    if not dry_run and not vm_exists(host, vmid, dry_run=dry_run):
        print(f"VM {vmid} does not exist; skipping")
        return

    if dry_run or vm_running(host, vmid, dry_run=dry_run):
        qm(host, ["stop", vmid, "--skiplock", 1], dry_run=dry_run)

    qm(
        host,
        ["destroy", vmid, "--purge", 1, "--destroy-unreferenced-disks", 1],
        dry_run=dry_run,
    )


def plan(proxmox, vms):
    print(f"Proxmox host: {proxmox['host']}")
    print(f"Storage: {proxmox['storage']}")
    print(f"Default bridge: {proxmox['bridge']}")
    print("")
    for vm in vms:
        print(f"{vm['vmid']} {vm['name']}")
        print(f"  memory: {vm['memory_mb']} MiB")
        print(f"  cores: {vm['cores']}")
        print(f"  os disk: {vm['os_disk_gb']}G")
        if vm["extra_disks_gb"]:
            print(f"  extra disks: {', '.join(str(size) + 'G' for size in vm['extra_disks_gb'])}")
        for index, nic in enumerate(vm["nics"]):
            print(f"  net{index}: {nic['model']} {nic['mac']} bridge={nic['bridge']}")
        print(f"  start: {'yes' if vm['start'] else 'no'}")


def parse_args():
    parser = argparse.ArgumentParser(description="Provision disposable Proxmox VMs for Flatcar lab testing.")
    parser.add_argument(
        "--config",
        default=str(ROOT / "flatcar" / "proxmox-lab.pkl"),
        help="lab config path, default: flatcar/proxmox-lab.pkl",
    )
    parser.add_argument("--dry-run", action="store_true", help="print qm commands instead of running them")
    parser.add_argument("action", choices=["plan", "up", "destroy", "recreate"])
    return parser.parse_args()


def main():
    args = parse_args()
    config_path = Path(args.config)
    proxmox, vms = load_config(config_path)

    if args.action == "plan":
        plan(proxmox, vms)
        return

    if args.action == "destroy":
        for vm in reversed(vms):
            destroy_vm(proxmox, vm, dry_run=args.dry_run)
        return

    if args.action == "recreate":
        for vm in reversed(vms):
            destroy_vm(proxmox, vm, dry_run=args.dry_run)
        for vm in vms:
            create_vm(proxmox, vm, dry_run=args.dry_run)
        return

    if args.action == "up":
        for vm in vms:
            create_vm(proxmox, vm, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
