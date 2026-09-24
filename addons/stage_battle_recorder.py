"""Focused mitmproxy addon that records LINE Rangers stage-battle exchanges.

The general game_api_logger dumps *every* request to one big transcript. This
addon does one thing well: it isolates the battle endpoints on rangers-api and
writes one clean JSON file per battle, pairing the /stage/enter response (which
carries the per-battle rsaKeyBase modulus + battleSn) with the /stage/save
request that follows (which carries the real, encrypted `battleKey` + `log`).

Attach it *alongside* game_api_logger on the reverse-mode rangers-api proxy:

    mitmdump --mode reverse:https://rangers-api.line-apps.com \
        --listen-port 9443 \
        -s addons/game_api_logger.py \
        -s addons/stage_battle_recorder.py \
        --set battle_dir=captures/battles

While you play, every captured save prints a loud banner to the console so you
know the recording worked before you stop. Nothing here modifies traffic - it
only observes and writes files.

Why this matters: /stage/save is the one endpoint we could never forge from the
API alone (the server re-simulates an AES-encrypted battle log wrapped with the
enter response's RSA modulus). Capturing one real save from a real play is the
missing plaintext-adjacent artifact - see memory lgrgs-stage-battle-api.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
from datetime import datetime

from mitmproxy import http

log = logging.getLogger("stage_battle_recorder")

# Path fragments that identify each battle endpoint. Matched as a substring of
# request.path so the /v12.3 prefix (or any future version) does not matter.
ENTER_FRAGMENTS = ("/stage/enter/", "/tutorial/stage/enter")
SAVE_FRAGMENTS = ("/stage/save/", "/tutorial/stage/save")
RESEND_FRAGMENTS = ("/stage/resend", "/tutorial/stage/resend")


def _body_view(raw: bytes, headers) -> dict:
    """JSON if it parses, else text, else base64 - always round-trippable."""
    if not raw:
        return {"kind": "empty", "size": 0}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "kind": "binary",
            "size": len(raw),
            "base64": base64.b64encode(raw).decode("ascii"),
            "hex_head": raw[:48].hex(),
        }
    stripped = text.strip()
    if stripped[:1] in ("{", "["):
        try:
            return {"kind": "json", "size": len(raw), "json": json.loads(stripped)}
        except ValueError:
            pass
    return {"kind": "text", "size": len(raw), "text": text}


def _json_of(view: dict):
    return view.get("json") if isinstance(view, dict) else None


def _dig(obj, *keys):
    """Walk nested dicts safely; returns None if any hop is missing."""
    cur = obj
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _find_key(obj, target):
    """Depth-first search for the first value under a key named `target`."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == target:
                return v
            found = _find_key(v, target)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_key(item, target)
            if found is not None:
                return found
    return None


class StageBattleRecorder:
    def __init__(self):
        self._lock = threading.Lock()
        self._dir = "captures/battles"
        self._enters = {}  # battleSn(str) -> stashed enter record
        self._last_enter = None  # fallback when a save has no matching sn
        self._saves = 0
        self._enters_seen = 0

    # -- lifecycle ---------------------------------------------------------

    def load(self, loader):
        loader.add_option(
            "battle_dir", str, "captures/battles",
            "Directory for the per-battle JSON files this addon writes.",
        )

    def running(self):
        from mitmproxy import ctx

        self._dir = ctx.options.battle_dir or "captures/battles"
        os.makedirs(self._dir, exist_ok=True)
        log.warning(
            "stage_battle_recorder: ARMED. Waiting for a stage battle. "
            "Per-battle files -> %s" % os.path.abspath(self._dir)
        )

    def done(self):
        log.warning(
            "stage_battle_recorder: stopped. entered=%d, saves captured=%d"
            % (self._enters_seen, self._saves)
        )

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _match(path: str, fragments) -> bool:
        low = (path or "").lower()
        return any(fr in low for fr in fragments)

    @staticmethod
    def _sn_and_stage_from_save_path(path: str):
        """`/v12.3/stage/save/{stageCode}/{battleSn}` -> (stageCode, battleSn)."""
        clean = (path or "").split("?", 1)[0]
        parts = [p for p in clean.split("/") if p]
        if "save" in parts:
            i = parts.index("save")
            stage = parts[i + 1] if i + 1 < len(parts) else None
            sn = parts[i + 2] if i + 2 < len(parts) else None
            return stage, sn
        return None, None

    @staticmethod
    def _stage_from_enter_path(path: str):
        clean = (path or "").split("?", 1)[0]
        parts = [p for p in clean.split("/") if p]
        if "enter" in parts:
            i = parts.index("enter")
            return parts[i + 1] if i + 1 < len(parts) else None
        return None

    def _write(self, name: str, record: dict) -> str:
        path = os.path.join(self._dir, name)
        with self._lock:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False, indent=2, default=str)
        return path

    # -- traffic hook ------------------------------------------------------

    def response(self, flow: http.HTTPFlow):
        try:
            self._handle(flow)
        except Exception as exc:  # never break the proxy on a bad body
            log.warning("stage_battle_recorder: skipped a flow (%s)" % exc)

    def _handle(self, flow: http.HTTPFlow):
        path = flow.request.path
        is_enter = self._match(path, ENTER_FRAGMENTS)
        is_save = self._match(path, SAVE_FRAGMENTS)
        is_resend = self._match(path, RESEND_FRAGMENTS)
        if not (is_enter or is_save or is_resend):
            return

        req_view = _body_view(flow.request.raw_content or b"", flow.request.headers)
        resp_view = _body_view(
            (flow.response.raw_content if flow.response else b"") or b"",
            flow.response.headers if flow.response else {},
        )
        status = flow.response.status_code if flow.response else None
        is_tutorial = "/tutorial/" in path.lower()
        kind = "tutorial" if is_tutorial else "stage"

        if is_enter:
            self._enters_seen += 1
            resp_json = _json_of(resp_view)
            battle_sn = _find_key(resp_json, "battleSn")
            modulus = _dig(resp_json, "result", "rsaKeyBase", "modulus")
            if modulus is None:
                modulus = _find_key(resp_json, "modulus")
            stage = self._stage_from_enter_path(path)
            enter_rec = {
                "kind": kind,
                "stageCode": stage,
                "battleSn": battle_sn,
                "path": path,
                "status": status,
                "request": req_view,
                "response": resp_view,
                "rsaKeyBase_modulus": modulus,
            }
            if battle_sn is not None:
                self._enters[str(battle_sn)] = enter_rec
            self._last_enter = enter_rec
            log.warning(
                "  [enter] %s  stage=%s  battleSn=%s  rsaKeyBase=%s"
                % (
                    kind,
                    stage,
                    battle_sn,
                    ("%d-char modulus" % len(str(modulus))) if modulus else "MISSING",
                )
            )
            return

        # save / resend --------------------------------------------------
        self._saves += 1
        stage, sn = self._sn_and_stage_from_save_path(path)
        enter_rec = None
        if sn is not None and str(sn) in self._enters:
            enter_rec = self._enters.get(str(sn))
        if enter_rec is None:
            enter_rec = self._last_enter  # best effort pairing

        req_json = _json_of(req_view)
        log_field = _find_key(req_json, "log") if req_json else None
        battle_key = _find_key(req_json, "battleKey") if req_json else None
        top_fields = sorted(req_json.keys()) if isinstance(req_json, dict) else None
        modulus = enter_rec.get("rsaKeyBase_modulus") if enter_rec else None
        resp_json = _json_of(resp_view)
        err = _find_key(resp_json, "errorCode") if resp_json else None

        analysis = {
            "save_top_level_fields": top_fields,
            "has_log": log_field is not None,
            "log_len": len(log_field) if isinstance(log_field, str) else None,
            "has_battleKey": battle_key is not None,
            "battleKey_len": len(battle_key) if isinstance(battle_key, str) else None,
            "paired_enter_found": enter_rec is not None
            and enter_rec.get("battleSn") is not None,
            "rsaKeyBase_modulus_len": len(str(modulus)) if modulus else None,
            "response_errorCode": err,
        }

        record = {
            "captured_at": datetime.now().isoformat(timespec="milliseconds"),
            "kind": kind,
            "is_resend": bool(is_resend),
            "stageCode": stage,
            "battleSn": sn,
            "save": {
                "path": path,
                "status": status,
                "request": req_view,
                "response": resp_view,
            },
            "enter": enter_rec,
            "analysis": analysis,
        }
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        fname = "%s_%s_%s_sn%s_%s.json" % (
            stamp,
            "resend" if is_resend else "save",
            stage or "unknown",
            sn or "none",
            status or "err",
        )
        out = self._write(fname, record)

        banner = [
            "",
            "=" * 68,
            "  BATTLE %s CAPTURED   kind=%s  stage=%s  sn=%s  status=%s"
            % ("RESEND" if is_resend else "SAVE", kind, stage, sn, status),
            "  log=%s (%s chars)   battleKey=%s (%s chars)   modulus=%s"
            % (
                analysis["has_log"],
                analysis["log_len"],
                analysis["has_battleKey"],
                analysis["battleKey_len"],
                analysis["rsaKeyBase_modulus_len"] or "no-enter",
            ),
            "  fields=%s" % (top_fields,),
            "  -> %s" % out,
            "=" * 68,
            "",
        ]
        log.warning("\n".join(banner))


addons = [StageBattleRecorder()]
