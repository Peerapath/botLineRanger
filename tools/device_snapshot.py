#!/usr/bin/env python3
"""Snapshot and diff the private files of the Android app com.linecorp.LGRGS.

On a rooted emulator, this tool captures a fingerprint (md5, size, mtime) of
every file under a set of app directories, plus the full text of small
shared_prefs XML files, so a human can see which files changed after doing
something in the app.

Subcommands:
  snap  Capture a snapshot of the default (or given) directories to a JSON file.
  diff  Compare two snapshots and print ADDED / REMOVED / CHANGED files.
  pull  Copy a single device file to the local machine (binary-safe via cp).

Only the Python standard library is used. adb is invoked via subprocess with a
list of arguments (never a shell string) because its path contains spaces.
"""

import argparse
import difflib
import json
import subprocess
import sys
from datetime import datetime, timezone

ADB = r"D:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe"
DEFAULT_SERIAL = "127.0.0.1:16384"

DEFAULT_DIRS = [
    "/data/data/com.linecorp.LGRGS/shared_prefs",
    "/data/data/com.linecorp.LGRGS/files",
    "/data/data/com.linecorp.LGRGS/databases",
    "/sdcard/Android/data/com.linecorp.LGRGS/files/.res/preload",
]

# Files under shared_prefs at or below this size get their full text captured.
PREFS_TEXT_MAX = 200000


def adb_run(args, serial):
    """Run an adb command, returning (returncode, stdout_text, stderr_text)."""
    cmd = [ADB, "-s", serial] + args
    proc = subprocess.run(cmd, capture_output=True)
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", errors="replace"),
        proc.stderr.decode("utf-8", errors="replace"),
    )


def run_adb(args, serial):
    """Run an adb command, returning stdout. Exits 1 on non-zero adb status."""
    rc, out, err = adb_run(args, serial)
    if rc != 0:
        sys.stderr.write(err)
        sys.stderr.write(f"\nadb command failed (exit {rc}): {args}\n")
        sys.exit(1)
    return out


def run_su(command, serial):
    """Run a privileged command on the device via su -c and return stdout text."""
    return run_adb(["shell", f"su -c '{command}'"], serial)


def run_su_find(command, serial):
    """Run a `find`-based su command, tolerating a missing directory.

    `find <missing-dir> ... 2>/dev/null` exits non-zero with empty output; that
    is a benign case meaning zero files, not a real failure. A non-zero exit
    with any output (or non-empty stderr) is treated as a genuine error.
    """
    rc, out, err = adb_run(["shell", f"su -c '{command}'"], serial)
    if rc != 0:
        if not out.strip() and not err.strip():
            return ""
        sys.stderr.write(err)
        sys.stderr.write(f"\nadb command failed (exit {rc}): {command}\n")
        sys.exit(1)
    return out


def parse_md5sum(text):
    """Parse 'md5sum' output into {path: md5}. Split on the first whitespace run."""
    result = {}
    for line in text.splitlines():
        line = line.rstrip("\r")
        if not line.strip():
            continue
        # md5sum format: "<md5> <space-or-*> <path>"
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        md5, path = parts
        # md5sum prefixes the path with a space (text mode) or '*' (binary mode)
        path = path.lstrip(" *").strip()
        if path:
            result[path] = md5
    return result


def parse_stat(text):
    """Parse 'stat -c "%s %Y %n"' output into {path: (size, mtime)}."""
    result = {}
    for line in text.splitlines():
        line = line.rstrip("\r")
        if not line.strip():
            continue
        parts = line.split(None, 2)
        if len(parts) != 3:
            continue
        try:
            size = int(parts[0])
            mtime = int(parts[1])
        except ValueError:
            continue
        path = parts[2]
        result[path] = (size, mtime)
    return result


def snapshot_dir(dir_path, serial):
    """Fingerprint all files under one directory. Returns {path: info}."""
    md5_by_path = parse_md5sum(
        run_su_find(f"find {dir_path} -type f -exec md5sum {{}} + 2>/dev/null", serial)
    )
    stat_by_path = parse_stat(
        run_su_find(f"find {dir_path} -type f -exec stat -c \"%s %Y %n\" {{}} + 2>/dev/null", serial)
    )

    files = {}
    for path, md5 in md5_by_path.items():
        size, mtime = stat_by_path.get(path, (0, 0))
        files[path] = {"md5": md5, "size": size, "mtime": mtime}
    return files


def capture_prefs_text(files, serial):
    """For small shared_prefs files, add their full text content under 'text'."""
    for path, info in files.items():
        if "/shared_prefs/" in path and info["size"] <= PREFS_TEXT_MAX:
            info["text"] = run_su(f"cat {path}", serial)


def cmd_snap(args):
    dirs = args.dirs if args.dirs else DEFAULT_DIRS
    all_files = {}
    per_dir_counts = {}
    for d in dirs:
        d_files = snapshot_dir(d, args.device)
        per_dir_counts[d] = len(d_files)
        all_files.update(d_files)

    capture_prefs_text(all_files, args.device)

    data = {
        "device": args.device,
        "taken": datetime.now(timezone.utc).isoformat(),
        "files": all_files,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)

    print(f"Snapshot written to {args.out} ({len(all_files)} files total)")
    for d in dirs:
        print(f"  {d}: {per_dir_counts[d]} files")


def cmd_diff(args):
    with open(args.before, "r", encoding="utf-8") as f:
        before = json.load(f)
    with open(args.after, "r", encoding="utf-8") as f:
        after = json.load(f)

    before_files = before.get("files", {})
    after_files = after.get("files", {})

    added = sorted(set(after_files) - set(before_files))
    removed = sorted(set(before_files) - set(after_files))
    changed = sorted(
        p for p in set(before_files) & set(after_files)
        if before_files[p]["md5"] != after_files[p]["md5"]
    )

    def show(path, files_map):
        info = files_map[path]
        print(f"  {path}  (size={info['size']}, mtime={info['mtime']})")

    print(f"ADDED ({len(added)}):")
    for p in added:
        show(p, after_files)

    print(f"REMOVED ({len(removed)}):")
    for p in removed:
        show(p, before_files)

    print(f"CHANGED ({len(changed)}):")
    for p in changed:
        show(p, after_files)

    if args.show_text:
        for p in added + changed:
            b_text = before_files.get(p, {}).get("text")
            a_text = after_files.get(p, {}).get("text")
            if b_text is None and a_text is None:
                continue
            b_lines = (b_text or "").splitlines()
            a_lines = (a_text or "").splitlines()
            diff = list(difflib.unified_diff(
                b_lines, a_lines,
                fromfile=f"a/{p}", tofile=f"b/{p}", lineterm="",
            ))
            if not diff:
                continue
            print(f"\n--- diff {p} ---")
            for line in diff[:200]:
                print(line)
            if len(diff) > 200:
                print(f"  ... ({len(diff) - 200} more lines truncated)")


def cmd_pull(args):
    # Git Bash (MSYS) rewrites a leading "/data/..." argument into "C:/Program Files/Git/data/...".
    # The device then reports a confusing "cp: not directory"; catch it here with the fix instead.
    if not args.device_path.startswith("/") or ":" in args.device_path:
        sys.exit(f"device_path {args.device_path!r} is not a device path - under Git Bash set "
                 f"MSYS_NO_PATHCONV=1 so /data/... is not rewritten to a Windows path")
    tmp = "/data/local/tmp/_snap_pull"
    run_su(f"cp {args.device_path} {tmp} && chmod 644 {tmp}", args.device)
    out = run_adb(["pull", tmp, args.local_path], args.device)
    sys.stderr.write(out)
    run_su(f"rm {tmp}", args.device)
    print(f"Pulled {args.device_path} -> {args.local_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Snapshot and diff private files of com.linecorp.LGRGS on a rooted emulator."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_snap = sub.add_parser("snap", help="Capture a snapshot to a JSON file.")
    p_snap.add_argument("--out", required=True, help="Output JSON file path.")
    p_snap.add_argument("--device", default=DEFAULT_SERIAL, help="adb device serial.")
    p_snap.add_argument("--dirs", nargs="+", default=None, help="Directories to snapshot.")
    p_snap.set_defaults(func=cmd_snap)

    p_diff = sub.add_parser("diff", help="Compare two snapshots.")
    p_diff.add_argument("before", help="Before snapshot JSON.")
    p_diff.add_argument("after", help="After snapshot JSON.")
    p_diff.add_argument("--show-text", action="store_true",
                        help="Print unified text diffs for changed/added text files.")
    p_diff.set_defaults(func=cmd_diff)

    p_pull = sub.add_parser("pull", help="Copy a device file to the local machine.")
    p_pull.add_argument("device_path", help="Path on the device.")
    p_pull.add_argument("local_path", help="Local destination path.")
    p_pull.add_argument("--device", default=DEFAULT_SERIAL, help="adb device serial.")
    p_pull.set_defaults(func=cmd_pull)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
