r"""Spawn LINE Rangers under a Frida hook and tee matching output to a scratch file.

Run this on the host with a rooted arm64 phone attached (frida-server running on it).
Then, in the app: WARP on -> GUEST Login -> agree the terms -> reach home. That drives
the native /login the hook is watching for. Do it TWICE (two fresh guests) so Task 2 can
diff the two appSecret values.

    python tools/frida/capture.py --script tools/frida/dump_login.js
    python tools/frida/capture.py --script tools/frida/dump_login.js --device <frida-id>

Needs: frida-python (host) + a matching frida-server on the phone. Standard library + frida.
"""
from __future__ import annotations
import argparse, os, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import frida

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRATCH = os.path.join(ROOT, "roster", "scratch")
PKG = "com.linecorp.LGRGS"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--script", required=True, help="path to the .js hook to load")
    parser.add_argument("--device", help="frida device id (default: first USB device)")
    parser.add_argument("--out", help="capture file (default roster/scratch/login-<ts>.capture.txt)")
    args = parser.parse_args()

    os.makedirs(SCRATCH, exist_ok=True)
    out = args.out or os.path.join(SCRATCH, "login-%s.capture.txt" % time.strftime("%Y%m%d-%H%M%S"))
    sink = open(out, "w", encoding="utf-8")
    print("device : %s" % (args.device or "first USB"))
    print("script : %s" % args.script)
    print("writing: %s" % out)

    device = frida.get_device(args.device) if args.device else frida.get_usb_device(timeout=10)
    pid = device.spawn([PKG])
    session = device.attach(pid)
    with open(args.script, "r", encoding="utf-8") as handle:
        script = session.create_script(handle.read())

    def on_message(message, data):
        line = message.get("payload") if message.get("type") == "send" else str(message)
        print(line, flush=True)
        sink.write(str(line) + "\n"); sink.flush()

    script.on("message", on_message)
    # console.log in the hook arrives as log messages too:
    script.set_log_handler(lambda level, text: (print(text, flush=True), sink.write(text + "\n"), sink.flush()))
    script.load()
    device.resume(pid)
    print("\napp resumed. Create the guest in-app now (WARP -> GUEST Login -> terms -> home).")
    print("Press Ctrl+C when the /login block has printed.\n")
    try:
        sys.stdin.read()
    except KeyboardInterrupt:
        pass
    finally:
        sink.close()
        print("saved %s" % out)


if __name__ == "__main__":
    main()
