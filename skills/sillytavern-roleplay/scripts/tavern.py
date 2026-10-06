#!/usr/bin/env python3
"""Local character-card and session storage for Codex. SPDX-License-Identifier: AGPL-3.0-only"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
import uuid
import zlib

MAX_CARD = 16 * 1024 * 1024
MAX_IMAGE = 64 * 1024 * 1024
PNG = b"\x89PNG\r\n\x1a\n"
TEXT_FIELDS = ("name", "description", "personality", "scenario", "first_mes",
               "mes_example", "system_prompt", "post_history_instructions",
               "creator", "creator_notes", "character_version")


class TavernError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(value):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value):
        raise TavernError("ID must be 1-64 lowercase ASCII letters, digits, underscores or hyphens.")
    if value.upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)],
                         *[f"LPT{i}" for i in range(1, 10)]}:
        raise TavernError("Reserved Windows filename cannot be an ID.")
    return value


def load_json(path, limit=MAX_CARD):
    path = Path(path)
    if path.stat().st_size > limit:
        raise TavernError(f"JSON exceeds {limit} bytes: {path.name}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


@contextmanager
def write_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".write.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise TavernError("Library is being written. Retry after the other command finishes; a stale lock needs inspection.") from exc
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def normalize_card(raw):
    if not isinstance(raw, dict):
        raise TavernError("Card JSON must be an object.")
    card = copy.deepcopy(raw)
    if "spec" not in card:
        card = {"spec": "chara_card_v2", "spec_version": "2.0", "data": card}
    if card["spec"] not in {"chara_card_v2", "chara_card_v3"}:
        raise TavernError("Only TavernAI V1 and Character Card V2/V3 are supported.")
    data = card.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("name"), str) or not data["name"].strip():
        raise TavernError("Card must have a non-empty character name.")
    for field in TEXT_FIELDS:
        data.setdefault(field, "")
        if not isinstance(data[field], str):
            raise TavernError(f"Card field {field} must be a string.")
    for field in ("alternate_greetings", "tags"):
        data.setdefault(field, [])
        if not isinstance(data[field], list) or any(not isinstance(x, str) for x in data[field]):
            raise TavernError(f"Card field {field} must be a list of strings.")
    if "extensions" in data and not isinstance(data["extensions"], dict):
        raise TavernError("Card extensions must be an object.")
    if data.get("character_book") is not None:
        normalize_book(data["character_book"])
    return card


def normalize_book(book):
    if not isinstance(book, dict):
        raise TavernError("Worldbook must be an object.")
    entries = book.get("entries", [])
    if isinstance(entries, dict):
        entries = list(entries.values())
    if not isinstance(entries, list) or any(not isinstance(x, dict) for x in entries):
        raise TavernError("Worldbook entries must be objects in a list or keyed object.")
    for entry in entries:
        if "extensions" in entry and not isinstance(entry["extensions"], dict):
            raise TavernError("Worldbook entry extensions must be an object.")
        if not isinstance(entry.get("content", ""), str):
            raise TavernError("Worldbook content must be text.")
        for key in ("keys", "key", "secondary_keys", "keysecondary"):
            if key in entry and (not isinstance(entry[key], list) or any(not isinstance(x, str) for x in entry[key])):
                raise TavernError(f"Worldbook {key} must be a list of strings.")
    book["entries"] = entries
    return book


def bounded_inflate(data):
    inflater = zlib.decompressobj()
    result = inflater.decompress(data, MAX_CARD + 1)
    if len(result) > MAX_CARD or inflater.unconsumed_tail or not inflater.eof:
        raise TavernError("Invalid or oversized compressed PNG metadata.")
    return result


def extract_png(blob):
    if not blob.startswith(PNG):
        raise TavernError("Not a PNG character card.")
    chunks = {}
    offset, ended = 8, False
    while offset < len(blob):
        if len(blob) - offset < 12:
            raise TavernError("Truncated PNG chunk header.")
        size = int.from_bytes(blob[offset:offset + 4], "big")
        kind = blob[offset + 4:offset + 8]
        end = offset + 8 + size
        if end + 4 > len(blob):
            raise TavernError("Truncated PNG chunk payload.")
        payload = blob[offset + 8:end]
        if kind in {b"tEXt", b"zTXt", b"iTXt"}:
            if zlib.crc32(kind + payload) & 0xffffffff != int.from_bytes(blob[end:end + 4], "big"):
                raise TavernError("PNG text chunk checksum is invalid.")
            key, sep, value = payload.partition(b"\x00")
            if sep and key in {b"chara", b"ccv3"}:
                if kind == b"zTXt":
                    if not value or value[0] != 0:
                        raise TavernError("Unsupported PNG compression method.")
                    value = bounded_inflate(value[1:])
                elif kind == b"iTXt":
                    if len(value) < 2 or value[0] not in (0, 1) or value[1] != 0:
                        raise TavernError("Invalid iTXt compression header.")
                    compressed, value = value[0], value[2:]
                    for _ in range(2):
                        _, sep, value = value.partition(b"\x00")
                        if not sep:
                            raise TavernError("Invalid iTXt language header.")
                    if compressed:
                        value = bounded_inflate(value)
                if len(value) > MAX_CARD:
                    raise TavernError("PNG card metadata is too large.")
                if key in chunks:
                    raise TavernError("Ambiguous PNG: duplicate character metadata chunks.")
                chunks[key] = value
        offset = end + 4
        if kind == b"IEND":
            ended = True
            break
    if not ended:
        raise TavernError("PNG is missing its IEND chunk.")
    selected = chunks.get(b"ccv3", chunks.get(b"chara"))
    if selected is None:
        raise TavernError("PNG contains no chara/ccv3 data; a normal portrait is not a character card.")
    try:
        decoded = base64.b64decode(selected.strip(), validate=True)
        return json.loads(decoded.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise TavernError("Character metadata is not valid base64 UTF-8 JSON.") from exc


def read_card(path):
    path = Path(path)
    if path.stat().st_size > MAX_IMAGE:
        raise TavernError("Card file is larger than 64 MiB.")
    with path.open("rb") as stream:
        signature = stream.read(8)
    if signature.startswith((b"RIFF", b"\xff\xd8", b"PK\x03\x04")):
        raise TavernError("WEBP, JPEG and CHARX are not supported; export a PNG or JSON character card.")
    raw = extract_png(path.read_bytes()) if signature == PNG else load_json(path)
    return normalize_card(raw)


def find_record(root, kind, query):
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", query):
        path = root / kind / f"{identifier(query)}.json"
        if path.is_file():
            return path, load_json(path, 128 * MAX_CARD)
    matches = []
    for path in sorted((root / kind).glob("*.json")):
        record = load_json(path, 128 * MAX_CARD)
        name = record["card"]["data"]["name"] if kind == "cards" else record["title"]
        names = [name, *record.get("aliases", [])] if kind == "cards" else [name]
        if any(item.casefold() == query.casefold() for item in names):
            matches.append((path, record))
    if len(matches) != 1:
        raise TavernError("Not found or name is ambiguous; use an ID from list/sessions.")
    return matches[0]


def render(text, char, user):
    # One pass: names containing macro-like text must not cause nested expansion.
    return re.sub(r"\{\{(char|user|original)\}\}",
                  lambda match: {"char": char, "user": user, "original": ""}[match[1]], text)


def entry_option(entry, key, default=None):
    return entry.get(key, entry.get("extensions", {}).get(key, default))


def select_lore(card, messages, user, max_chars=12000):
    book = card["data"].get("character_book") or {}
    entries = book.get("entries", [])
    selected, warnings = [], []
    char = card["data"]["name"]
    try:
        depth = max(0, min(100, int(book.get("scan_depth", 4))))
    except (TypeError, ValueError):
        depth = 4
    for index, entry in enumerate(entries):
        if entry.get("enabled", True) is False or entry.get("disable", False):
            continue
        keys = entry.get("keys", entry.get("key", []))
        secondary = entry.get("secondary_keys", entry.get("keysecondary", []))
        if not entry.get("constant") and (entry.get("use_regex") or any(re.fullmatch(r"/.+/[a-z]*", key) for key in keys + secondary)):
            warnings.append(f"Worldbook entry {index}: regex matching unsupported; skipped.")
            continue
        try:
            local_depth = max(0, min(100, int(entry_option(entry, "scan_depth", entry_option(entry, "scanDepth", depth)))))
        except (ValueError, TypeError):
            local_depth = depth
        scan = "\n".join(messages[-local_depth:]) if local_depth else ""
        sensitive = entry_option(entry, "case_sensitive", entry_option(entry, "caseSensitive", False))
        if not sensitive:
            scan = scan.casefold()
        whole = entry_option(entry, "match_whole_words", entry_option(entry, "matchWholeWords", False))
        def matches(key):
            key = render(key, char, user)
            key = key if sensitive else key.casefold()
            if not key:
                return False
            return bool(re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", scan)) if whole else key in scan
        active = bool(entry.get("constant")) or any(matches(key) for key in keys)
        if active and not entry.get("constant") and entry.get("selective") and secondary:
            hits = [matches(key) for key in secondary]
            logic = entry_option(entry, "selectiveLogic", 0)
            if logic not in (0, 1, 2, 3):
                warnings.append(f"Worldbook entry {index}: unknown optional-filter logic; skipped.")
                continue
            active = {0: any(hits), 1: not all(hits), 2: not any(hits), 3: all(hits)}[logic]
        if not active:
            continue
        content = render(entry.get("content", ""), char, user)
        try:
            order = float(entry.get("insertion_order", entry.get("order", 100)))
        except (ValueError, TypeError):
            order = 100
        selected.append({"index": index, "constant": bool(entry.get("constant")), "order": order,
                         "position": entry.get("position", "before_char"), "content": content})
    chosen, used = [], 0
    for entry in sorted(selected, key=lambda item: (not item["constant"], -item["order"], item["index"])):
        if used + len(entry["content"]) > max_chars:
            warnings.append(f"Worldbook entry {entry['index']}: context character budget exceeded; skipped.")
            continue
        used += len(entry["content"])
        chosen.append(entry)
    chosen.sort(key=lambda item: (item["order"], item["index"]))
    return chosen, warnings


def card_warnings(card):
    data = card["data"]
    warnings = []
    if data.get("extensions") or data.get("assets"):
        warnings.append("Frontend extensions/assets are preserved as data; scripts, regex transforms, MVU and external assets are not executed.")
    if (data.get("character_book") or {}).get("recursive_scanning"):
        warnings.append("Recursive worldbook activation is unsupported; using direct keyword activation.")
    return warnings


def context(session, incoming="", max_chars=12000):
    card = session["card_snapshot"]
    data = card["data"]
    messages = [part for turn in session["turns"] for part in (turn.get("user", ""), turn["assistant"]) if part]
    if incoming:
        messages.append(incoming)
    lore, warnings = select_lore(card, messages, session["user_name"], max_chars)
    return {"session_id": session["id"], "revision": session["revision"], "status": session["status"],
            "mode": session["mode"], "user_name": session["user_name"],
            "character": {field: render(data[field], data["name"], session["user_name"]) for field in TEXT_FIELDS},
            "lore": lore, "summary": session["summary"], "scene": session["scene"],
            "relationships": session["relationships"], "memories": session["memories"], "facts": session["facts"],
            "memory_scope": session["id"], "recent_turns": session["turns"][-6:], "incoming": incoming,
            "warnings": card_warnings(card) + warnings}


def run(args):
    root = Path(args.root).expanduser().resolve()
    cmd = args.command
    if cmd == "import":
        card = read_card(args.file)
        aliases = list(dict.fromkeys(alias.strip() for alias in args.alias))
        if any(not alias or len(alias) > 200 for alias in aliases):
            raise TavernError("Aliases must be non-empty text of at most 200 characters.")
        if args.lore_file:
            book = normalize_book(load_json(args.lore_file))
            existing = card["data"].get("character_book") or {"entries": []}
            card["data"]["character_book"] = {**book, "entries": existing["entries"] + book["entries"]}
        digest = hashlib.sha256(json.dumps(card, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        slug = re.sub(r"[^a-z0-9]+", "-", card["data"]["name"].lower()).strip("-")[:40] or "character"
        card_id = identifier(args.id or f"{slug}-{digest[:10]}")
        with write_lock(root):
            target = root / "cards" / f"{card_id}.json"
            if target.exists():
                old = load_json(target)
                if old["digest"] != digest:
                    raise TavernError("That card ID already exists with different data; choose another --id.")
                combined = list(dict.fromkeys(old.get("aliases", []) + aliases))
                if combined != old.get("aliases", []):
                    old["aliases"] = combined
                    atomic_json(target, old)
                aliases = combined
            else:
                atomic_json(target, {"id": card_id, "digest": digest, "imported_at": now(),
                                    "source": str(Path(args.file).resolve()), "aliases": aliases, "card": card})
        return {"card_id": card_id, "name": card["data"]["name"], "path": str(target), "root": str(root),
                "aliases": aliases, "greetings": 1 + len(card["data"]["alternate_greetings"]), "warnings": card_warnings(card)}
    if cmd in ("list", "sessions"):
        result = []
        kind = "cards" if cmd == "list" else "sessions"
        for path in sorted((root / kind).glob("*.json")):
            item = load_json(path, 128 * MAX_CARD)
            if kind == "cards":
                result.append({"id": item["id"], "name": item["card"]["data"]["name"], "aliases": item.get("aliases", [])})
            elif not args.card or item["card_id"] == find_record(root, "cards", args.card)[1]["id"]:
                result.append({key: item[key] for key in ("id", "title", "card_id", "mode", "status", "updated_at")})
        return {"root": str(root), kind: result}
    if cmd in ("show", "export", "preview", "start"):
        _, record = find_record(root, "cards", args.card)
        card = record["card"]
        if cmd == "show":
            return {"card_id": record["id"], "card": card, "warnings": card_warnings(card)}
        if cmd == "export":
            target = Path(args.output).resolve()
            if target.exists():
                raise TavernError("Export destination exists; choose a new filename.")
            atomic_json(target, card)
            return {"exported": str(target)}
        greetings = [card["data"]["first_mes"], *card["data"]["alternate_greetings"]]
        if args.greeting < 0 or args.greeting >= len(greetings):
            raise TavernError("Greeting index is out of range (0 is the main opening).")
        greeting = render(greetings[args.greeting], card["data"]["name"], args.user)
        session = {"id": uuid.uuid4().hex[:16], "revision": 0, "card_id": record["id"], "card_snapshot": card,
                   "title": args.title or f"{card['data']['name']} · {args.user}", "user_name": args.user,
                   "mode": args.mode, "status": "active", "summary": "", "scene": "", "relationships": {},
                   "memories": [], "facts": {}, "created_at": now(), "updated_at": now(),
                   "turns": [{"turn_id": "opening", "user": "", "assistant": greeting}] if greeting else []}
        if cmd == "start":
            with write_lock(root):
                atomic_json(root / "sessions" / f"{session['id']}.json", session)
        return {"root": str(root), "persistent": cmd == "start", "greeting": greeting, "context": context(session)}
    if cmd in ("prepare", "resume", "stop", "commit"):
        incoming = Path(args.message_file).read_text(encoding="utf-8-sig") if cmd == "prepare" and args.message_file else ""
        if cmd == "prepare":
            _, session = find_record(root, "sessions", args.session)
            if session["status"] != "active":
                raise TavernError("Session is paused; resume it first.")
            return context(session, incoming, args.lore_chars)
        with write_lock(root):
            target, session = find_record(root, "sessions", args.session)
            if cmd == "commit":
                payload = load_json(args.turn_file)
                if not isinstance(payload, dict):
                    raise TavernError("Turn file must be a JSON object.")
                turn_id = payload.get("turn_id")
                if not isinstance(turn_id, str) or not turn_id or len(turn_id) > 100 or turn_id == "opening":
                    raise TavernError("Turn requires a unique turn_id (not 'opening').")
                fingerprint = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                duplicate = next((turn for turn in session["turns"] if turn["turn_id"] == turn_id), None)
                if duplicate:
                    if duplicate.get("fingerprint") != fingerprint:
                        raise TavernError("This turn_id was already used for different content.")
                    return {"session_id": session["id"], "revision": session["revision"], "already_saved": True}
                if session["status"] != "active":
                    raise TavernError("Session is paused; resume it first.")
                expected = payload.get("expected_revision")
                if type(expected) is not int or expected != session["revision"]:
                    raise TavernError("Session changed; prepare again and reconcile the new state before committing.")
                for key in ("user", "assistant"):
                    if not isinstance(payload.get(key), str) or not payload[key].strip():
                        raise TavernError(f"Turn requires non-empty {key} text.")
                update = payload.get("update", {})
                if not isinstance(update, dict) or set(update) - {"summary", "scene", "memories", "facts", "relationships"}:
                    raise TavernError("Unsupported session update field.")
                for key, value in update.items():
                    expected_type = str if key in {"summary", "scene"} else list if key == "memories" else dict
                    if not isinstance(value, expected_type):
                        raise TavernError(f"Session update {key} has the wrong type.")
                    if key == "memories":
                        if any(not isinstance(item, str) for item in value):
                            raise TavernError("Memories must be a list of text items.")
                        session[key] = list(dict.fromkeys(session[key] + value))
                    elif key in {"facts", "relationships"}:
                        session[key].update(value)
                    else:
                        session[key] = value
                session["turns"].append({"turn_id": turn_id, "fingerprint": fingerprint, "saved_at": now(),
                                         "user": payload["user"], "assistant": payload["assistant"]})
            else:
                session["status"] = "active" if cmd == "resume" else "paused"
            session["revision"] += 1
            session["updated_at"] = now()
            atomic_json(target, session)
        return context(session) if cmd == "resume" else {"session_id": session["id"], "revision": session["revision"],
                                                        "status": session["status"], "path": str(target)}
    raise TavernError("Unknown command.")


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--root", default=str(Path(__file__).resolve().parents[3] / "database" / "roleplay-library"),
                     help="Independent data library; use an explicit path if your Documents folder is redirected.")
    commands = cli.add_subparsers(dest="command", required=True)
    command = commands.add_parser("import")
    command.add_argument("file")
    command.add_argument("--id")
    command.add_argument("--alias", action="append", default=[], help="Additional name; repeat for multiple aliases.")
    command.add_argument("--lore-file")
    commands.add_parser("list")
    command = commands.add_parser("sessions")
    command.add_argument("--card")
    for action in ("show", "export", "preview", "start"):
        command = commands.add_parser(action)
        command.add_argument("card")
        if action == "export":
            command.add_argument("output")
        elif action in ("preview", "start"):
            command.add_argument("--user", default="你")
            command.add_argument("--mode", choices=("play", "soul"), default="play")
            command.add_argument("--greeting", type=int, default=0)
            command.add_argument("--title", default="")
    for action in ("prepare", "resume", "stop", "commit"):
        command = commands.add_parser(action)
        command.add_argument("session")
        if action == "prepare":
            command.add_argument("--message-file")
            command.add_argument("--lore-chars", type=int, default=12000)
        elif action == "commit":
            command.add_argument("turn_file")
    return cli


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        result = run(parser().parse_args())
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (TavernError, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
