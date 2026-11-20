#!/usr/bin/env python3
"""rezip.py [<zip> <dist|preload>]: rebuild one of stage 1's ZIPs as the CI's Info-ZIP wrote it.

`zip -r` adds files in the builder filesystem's readdir order and records each file's mtime, atime, uid and
gid, none of which a rebuild repeats. zip-metadata.json holds those, read from the ZIPs spruce's cores embed.
This unpacks the freshly built ZIP, checks it has the same files and contents, gives every entry its recorded
mode, times and owner, and zips the entries again in the recorded order. Without arguments it only checks that
the metadata loads (the recipe runs it once as a patch step, which keeps this folder mounted for the build).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

META = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "zip-metadata.json")))

if len(sys.argv) == 1:
    print("rezip: metadata for " + ", ".join(f"{k} ({len(v['entries'])} entries)" for k, v in META.items()))
    sys.exit(0)

path, key = os.path.abspath(sys.argv[1]), sys.argv[2]
entries = META[key]["entries"]
built = zipfile.ZipFile(path)
have = {i.filename: (f"{i.CRC:08x}", i.file_size) for i in built.infolist()}
want = {e["name"]: (e["crc"], e["size"]) for e in entries}
if set(have) != set(want):
    sys.exit(f"rezip {key}: entries differ: only built {sorted(set(have) - set(want))[:5]}, only recorded {sorted(set(want) - set(have))[:5]}")
bad = [n for n in want if not n.endswith("/") and have[n] != want[n]]
if bad:
    sys.exit(f"rezip {key}: contents differ for {bad[:5]}")

work = tempfile.mkdtemp(prefix=f"rezip-{key}-")
built.extractall(work)
built.close()
# Times last, deepest first, so setting them is the final change to each directory.
for e in entries:
    p = os.path.join(work, e["name"])
    os.chown(p, e["uid"], e["gid"])
    os.chmod(p, e["mode"] & 0o7777)
for e in sorted(entries, key=lambda e: -e["name"].rstrip("/").count("/")):
    os.utime(os.path.join(work, e["name"]), (e["atime"], e["mtime"]))
os.remove(path)
names = "".join(e["name"] + "\n" for e in entries)
subprocess.run(["zip", "-q", path, "-@"], input=names, text=True, cwd=work, check=True)
shutil.rmtree(work)
got = [i.filename for i in zipfile.ZipFile(path).infolist()]
if got != [e["name"] for e in entries]:
    sys.exit(f"rezip {key}: zip did not keep the recorded order")
sha = __import__("hashlib").sha256(open(path, "rb").read()).hexdigest()
print(f"rezip {key}: {len(entries)} entries, sha256 {sha} ({'= spruce' if sha == META[key]['sha256_in_spruce'] else 'differs from spruce ' + META[key]['sha256_in_spruce']})")
