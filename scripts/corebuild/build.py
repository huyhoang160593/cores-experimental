"""Run builds in the pinned toolchain images and record what came out."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

from . import recipe
from .catalog import Repo, known_good
from .variants import Variant

# retro_deinit is recorded but not required: some cores crash there when no game was loaded.
SMOKE_STEPS = ("dlopen", "retro_api_version", "retro_set_environment", "retro_init",
               "retro_get_system_info")
CHECK = re.compile(r"CHECK (\S+) (pass|fail)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect(ref: str, fmt: str) -> str | None:
    if shutil.which("docker") is None:
        raise RuntimeError("docker is not on PATH")
    result = subprocess.run(["docker", "image", "inspect", "--format", fmt, ref],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def alias(image_id: str) -> str:
    """The tag load_toolchain gives an image whose local ID is not its config digest."""
    return "cores-toolchain:" + image_id.split(":", 1)[1]


def image_ref(image_id: str) -> str | None:
    """The docker reference of the loaded image whose config digest is image_id, or None.

    The classic image store's IDs are config digests; the containerd store (Docker 29's default) uses
    manifest digests, so there load_toolchain tags the image with alias(image_id)."""
    if _inspect(image_id, "{{.Id}}") == image_id:
        return image_id
    ref = alias(image_id)
    return ref if _inspect(ref, "{{.Id}}") is not None else None


def image_present(image_id: str) -> bool:
    return image_ref(image_id) is not None


class _Tee:
    def __init__(self, source, sink):
        self.source, self.sink = source, sink

    def read(self, size=-1):
        data = self.source.read(size)
        if data:
            self.sink.write(data)
        return data


def load_toolchain(archive: Path, image_id: str) -> str:
    """docker load a `docker save` .tar.gz, check it against image_id on either image store, return its ref.

    The archive's config must hash to image_id, and the loaded image must have that config's layers."""
    if shutil.which("docker") is None:
        raise RuntimeError("docker is not on PATH")
    small = {}
    gunzip = subprocess.Popen(["gunzip", "-c", str(archive)], stdout=subprocess.PIPE)
    load = subprocess.Popen(["docker", "load"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    tee = _Tee(gunzip.stdout, load.stdin)
    unreadable = None
    try:
        with tarfile.open(fileobj=tee, mode="r|") as tar:
            for member in tar:
                if member.isfile() and member.size < (1 << 20):
                    small[member.name.removeprefix("./")] = tar.extractfile(member).read()
        while tee.read(1 << 20):
            pass
    except tarfile.TarError as error:
        unreadable = error
    except BrokenPipeError:
        pass  # docker load stopped reading; its exit status and output say why
    finally:
        gunzip.stdout.close()
        try:
            load.stdin.close()
        except BrokenPipeError:
            pass
    with load.stdout:
        output = load.stdout.read().decode(errors="replace")
    gunzip_status, load_status = gunzip.wait(), load.wait()
    if unreadable is not None:
        raise RuntimeError(f"{archive.name} is not a tar archive ({unreadable})")
    if gunzip_status != 0 or load_status != 0:
        raise RuntimeError(f"docker load failed: {output.strip()}")
    try:
        entry = json.loads(small["manifest.json"])[0]
        config = small[entry["Config"]]
    except (KeyError, IndexError, ValueError) as error:
        raise RuntimeError(f"{archive.name} is not a docker save archive ({error})") from None
    digest = "sha256:" + hashlib.sha256(config).hexdigest()
    if digest != image_id:
        raise RuntimeError(f"{archive.name} holds image {digest}, not {image_id}")
    loaded = re.findall(r"^Loaded image(?: ID)?: (\S+)$", output, re.M)
    if not loaded:
        raise RuntimeError(f"docker load named no image: {output.strip()}")
    layers = _inspect(loaded[0], "{{json .RootFS.Layers}}")
    if layers is None or json.loads(layers) != json.loads(config)["rootfs"]["diff_ids"]:
        raise RuntimeError(f"{loaded[0]} does not have the layers of {image_id}")
    if image_ref(image_id) is None:
        subprocess.run(["docker", "tag", loaded[0], alias(image_id)], check=True, capture_output=True)
    ref = image_ref(image_id)
    if ref is None:
        raise RuntimeError(f"{image_id} is not reachable after loading {archive.name}")
    return ref


def run_container(repo: Repo, image_id: str, script: recipe.Script, out: Path,
                  cpus: str | None = None, platform: str | None = None) -> int:
    ref = image_ref(image_id)
    if ref is None:
        raise RuntimeError(f"toolchain image {image_id} is not loaded")
    out.mkdir(parents=True)
    (out / "script.sh").write_text(script.text)
    command = ["docker", "run", "--rm", "-e", f"OUTPUT_UID={os.getuid()}",
               "-e", f"OUTPUT_GID={os.getgid()}", "-v", f"{out.resolve()}:/output"]
    if cpus:
        command += ["--cpuset-cpus", cpus]
    if platform:  # an image for another architecture, run under qemu
        command += ["--platform", platform]
    for host, container in script.mounts:
        command += ["-v", f"{(repo.root / host).resolve()}:{container}:ro"]
    command += [ref, "bash", "-lc", script.text]
    with (out / "build.log").open("w") as log:
        return subprocess.run(command, stdout=log, stderr=subprocess.STDOUT).returncode


def usability(out: Path) -> dict:
    """Parse the smoke loader's CHECK lines into a verdict."""
    smoke = out / "smoke.txt"
    if not smoke.exists():
        return {"probed": False}
    # A core may print to stdout without a newline, so a CHECK can start mid-line.
    checks = dict(CHECK.findall(smoke.read_text(errors="replace")))
    loaded = all(checks.get(step) == "pass" for step in SMOKE_STEPS)
    return {"probed": True, "loaded": loaded, "checks": checks}


def variant_calls(out: Path) -> dict | None:
    log = out / "variant-calls.log"
    if not log.exists():
        return None
    calls = log.read_text(errors="replace").splitlines()
    compiles = sum(1 for call in calls if " -c " in f" {call} ")
    return {"calls": len(calls), "compiles": compiles}


def build_one(repo: Repo, core: str, variant: Variant, out: Path, repeat: int = 1,
              spec: dict | None = None) -> dict:
    spec = spec or repo.cores[core]
    toolchain = repo.toolchains[recipe.toolchain_for(spec, variant.arch)]
    script = recipe.render(core, spec, variant.arch, variant)
    started = time.time()
    exit_code = run_container(repo, toolchain["image_id"], script, out)
    artifact = out / spec["build"]["artifact_name"]
    metadata = out / spec["metadata"]["artifact_name"]
    record = {
        "core": core,
        "variant": variant.describe(),
        "source": spec["source"],
        "toolchain": {"image": toolchain["image"], "image_id": toolchain["image_id"]},
        "exit_code": exit_code,
        "seconds": round(time.time() - started, 1),
        "host": platform.node(),
        "artifact": None,
        "metadata": None,
    }
    if artifact.is_file() and artifact.stat().st_size > 0:
        record["artifact"] = {"name": artifact.name, "sha256": sha256(artifact),
                              "size": artifact.stat().st_size}
    if metadata.is_file():
        record["metadata"] = {"name": metadata.name, "sha256": sha256(metadata)}
    record["usability"] = usability(out)
    record["variant_calls"] = variant_calls(out)
    record["status"] = status(record)
    if repeat > 1 and record["artifact"]:
        # A freeze must not depend on timing or parallelism: rebuild on half the CPUs.
        again = out / "repeat"
        cpus = os.cpu_count() or 1
        run_container(repo, toolchain["image_id"], script, again,
                      cpus=f"0-{max(0, cpus // 2 - 1)}" if cpus > 1 else None)
        second = again / artifact.name
        record["repeat_sha256"] = sha256(second) if second.is_file() else None
        record["reproducible"] = record["repeat_sha256"] == record["artifact"]["sha256"]
    (out / "record.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def status(record: dict) -> str:
    # The smoke step never fails the script, so a non-zero exit is a build step failing.
    if not record["artifact"] or record["exit_code"] != 0:
        return "failed"
    use = record["usability"]
    if not use["probed"]:
        return "built"
    return "usable" if use["loaded"] else "unusable"


def build_core(repo: Repo, core: str, variants: list[Variant], out: Path, repeat: int = 1,
               fallback: bool = False) -> list[dict]:
    """Build each variant; with `fallback`, retry a failed one at the known-good recipe."""
    records = []
    previous = known_good(repo.cores[core]) if fallback else None
    for variant in variants:
        target = out / core / variant.name
        failed = target.with_name(target.name + ".current")
        for stale in (target, failed):
            if stale.exists():
                shutil.rmtree(stale)
        print(f"== {core} {variant.name} ({' '.join(variant.flags) or 'catalog flags'})", flush=True)
        record = build_one(repo, core, variant, target, repeat)
        if previous and record["status"] in ("failed", "unusable"):
            print(f"   {record['status']} at {record['source']['commit'][:12]}; trying known-good "
                  f"{previous['source']['commit'][:12]}", flush=True)
            target.rename(failed)
            record = build_one(repo, core, variant, target, repeat, spec=previous)
            failed.rename(target / "current-attempt")
            record["fallback"] = {"from_commit": repo.cores[core]["source"]["commit"]}
            (target / "record.json").write_text(json.dumps(record, indent=2) + "\n")
        print(f"   {record['status']} in {record['seconds']}s", flush=True)
        records.append(record)
    return records
