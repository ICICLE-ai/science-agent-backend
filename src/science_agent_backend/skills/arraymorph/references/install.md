# In-pod installation instructions

Sources reviewed 2026-10-10:
- https://github.com/ICICLE-ai/ArrayMorph
- https://github.com/ICICLE-ai/ArrayMorph/blob/main/src/arraymorph/__init__.py

## Inspect first (no installation or cloud writes)

Check OS, architecture, Python version, available disk space, and whether the
chosen environment already has ArrayMorph. Never dump the process environment.

```sh
uname -sm
python3 --version
df -h "$HOME"
```

## Isolated setup (only when setup is requested)

Use a dedicated environment; do not modify the running agent's interpreter.

```sh
python3 -m venv "$HOME/.science-agent/envs/arraymorph"
"$HOME/.science-agent/envs/arraymorph/bin/python" -m pip install --upgrade pip
"$HOME/.science-agent/envs/arraymorph/bin/python" -m pip install --only-binary=:all: arraymorph numpy pillow
"$HOME/.science-agent/envs/arraymorph/bin/python" -m pip freeze
```

Record actual installed versions for reproducibility. No compatible wheel means
stop and report it, not silently compile or alter system libraries. The upstream
source build uses vcpkg, CMake, Ninja, and h5py's bundled HDF5 library; consult the
upstream README for the current build procedure. Native HDF5 ABI compatibility
must be checked with a real connector operation, not merely an import.

### Published 0.2.0b4 compatibility

The currently published wheel is 0.2.0b4. Our real ARM Docker and x86 pod probes
found native teardown crashes. The dedicated roundtrip.py probe uses the
existing bundled-HDF5 C API helper and disposable subprocesses that explicitly
close dataset/file handles, flush evidence, and bypass faulty native teardown.
It does not establish that ordinary h5py usage is stable. For this wheel only,
configure_s3(addressing_style=False) gives the required path-style URL; this
differs from the current README's API intent. Do not apply it to future versions
without retesting. Its native TLS client also requires
/etc/pki/tls/certs/ca-bundle.crt; if absent, link the existing system CA bundle
there with appropriate permission. Never disable certificate verification.

The opt-in install_probe.py installs an isolated environment and runs the real
probe. It receives private s3.key and nonsecret probe-config.json files, deletes
the credential file on completion, and writes a secret-free result.json. This
probe is separate from the chat workflow, not an automatic upload feature.

## Configure ICICLE S3 in the storage subprocess

The standard ArrayMorph reads S3 settings from ~/.arraymorph/config,
but this deployment avoids that file for security reasons and
uses per-user credentials stored encrypted in PostgreSQL.

Use the selected user credential delivered in the private request context from
PostgreSQL. If no credential is selected, ask the user to select one in Settings.
Do not read global AWS environment values, ~/.aws files, or a local service key
as a fallback. The pinned 0.2.0b4 worker is configured from that profile:

```python
import arraymorph

profile = request_context["s3"]
arraymorph.configure_s3(
    bucket=profile["bucket"],
    access_key=profile["access_key_id"],
    secret_key=profile["secret_access_key"],
    endpoint=profile["endpoint"],
    region=profile["region"],
    use_tls=True,
    addressing_style=False,
    use_signed_payloads=True,
)
arraymorph.enable()
import h5py
import numpy as np
```

The Python API above configures environment variables. Do not follow the
~/.arraymorph/config instructions in the standard ArrayMorph README
for this deployement.

## Verification before uploaded-image processing

With explicit permission for a cloud write, create a tiny chunked uint8 dataset
under a unique session/run name using h5py with the enabled connector. Close it,
then read it back in a fresh subprocess with the same configuration and compare
the bytes. Verify cloud objects under that exact prefix using an authorized
bucket-scoped S3 client; a local HDF5 round trip alone is insufficient evidence.
Do not use ListBuckets as a connectivity gate. Preserve evidence and report any
403, plugin-load or ABI failure without claiming success.

After this passes, store uploaded original bytes as a chunked uint8 dataset,
read them back, reconstruct the original extension and compare SHA256 against
the upload manifest. Pixel arrays may be stored additionally if requested.
Smart Labeler still needs the reconstructed image staged on its Tapis system;
ArrayMorph installation does not implement that staging or job submission.
