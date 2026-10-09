#!/usr/bin/python3
"""Scan one feeder stack and publish one complete PDF to Paperless."""

import datetime
import fcntl
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import img2pdf


def publish(pdf: Path, destination: Path) -> None:
    # Kubernetes subPath mounts cannot be renamed across, even on one PVC.
    # Paperless ignores the unsupported .tmp suffix while the copy is written.
    with tempfile.NamedTemporaryFile(
        prefix='.paperless-scanner-', suffix='.tmp', dir=destination.parent, delete=False,
    ) as output:
        staged = Path(output.name)
        try:
            with pdf.open('rb') as source:
                shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())
        except Exception:
            staged.unlink(missing_ok=True)
            raise
    try:
        # Publish within the consume mount so the rename is atomic.
        os.replace(staged, destination)
    finally:
        staged.unlink(missing_ok=True)


def scan(spool: Path, consume: Path, device: str) -> bool:
    spool.mkdir(parents=True, exist_ok=True)
    consume.mkdir(parents=True, exist_ok=True)
    with (spool / 'scan.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.warning('Ignoring button press while a scan is already running')
            return False

        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        job = Path(tempfile.mkdtemp(prefix=f'Brother-{timestamp}-', dir=spool))
        logging.info('Scanning feeder into %s', job)
        try:
            result = subprocess.run(
                [
                    'scanimage',
                    # Use the Brother device passed by brscan-skey. AirScan
                    # starts an independent session while the printer is
                    # waiting for its proprietary scan-to-PC connection.
                    '--device-name', device,
                    '--source', 'Automatic Document Feeder(center aligned)',
                    '--mode', 'True Gray',
                    '--resolution', '300',
                    '--format=tiff',
                    f'--batch={job}/page-%04d.tiff',
                ],
                timeout=900,
                check=False,
            )
            pages = sorted(job.glob('page-*.tiff'))
            # SANE status 7 means the feeder is empty after the last page.
            if result.returncode not in (0, 7):
                raise RuntimeError(f'scanimage exited with status {result.returncode}')
            if not pages:
                job.rmdir()
                logging.info('Feeder is empty; no document submitted')
                return False

            pdf = job / 'document.pdf'
            with pdf.open('wb') as output:
                output.write(img2pdf.convert(*(str(page) for page in pages)))
                output.flush()
                os.fsync(output.fileno())
            destination = consume / f'{job.name}.pdf'
            publish(pdf, destination)
            logging.info('Submitted %d pages to Paperless: %s', len(pages), destination.name)
            shutil.rmtree(job)
            return True
        except Exception:
            logging.exception('Scan failed; retaining files for recovery in %s', job)
            return False


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if len(sys.argv) < 2 or not sys.argv[1].startswith('brother5:'):
        raise SystemExit('Expected the Brother SANE device from brscan-skey')
    raise SystemExit(0 if scan(Path('/scan-spool'), Path('/consume'), sys.argv[1]) else 1)
