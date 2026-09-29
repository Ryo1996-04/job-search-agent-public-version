"""Privacy scan: nothing personal may be committed to this repository.

This repo was extracted from a private project that holds a real person's resume
data. The scan is the guarantee that none of it came along, and that none of it
arrives later. Two layers:

1. Pattern checks that need no list: email addresses, phone numbers, home-directory
   paths, LinkedIn profile URLs, links to hosts outside an allowlist, and files that
   must never be tracked (PDF/Word documents, a real bank, the private data folders).

2. A denylist of terms specific to the author - names, employers, schools, places,
   figures - stored only as salted SHA-256 hashes in tools/denylist.sha256. The
   plaintext list lives outside the repository. The scan hashes every 1-4 word
   phrase, and every 2-16 character run of CJK text, in every file and compares.

A hash cannot be read back, but anyone who already suspects a term can confirm it.
That is acceptable here: the list guards against leaks, not against guesses.

Usage:
    python tools/privacy_scan.py                    scan the repo; exit 1 on findings
    python tools/privacy_scan.py --staged           scan staged files (pre-commit hook)
    python tools/privacy_scan.py --hash-terms FILE  rebuild denylist.sha256 from a
                                                    plaintext list kept OUTSIDE the repo
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DENYLIST = ROOT / "tools" / "denylist.sha256"
SALT = "resume-fact-gate/privacy/v1:"
MAX_WORDS = 4
CJK_MIN, CJK_MAX = 2, 16

CJK = "㐀-䶿一-鿿豈-﫿"
TOKEN = re.compile(rf"[a-z0-9]+|[{CJK}]+")

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})")
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net",
                         "users.noreply.github.com"}

# Shapes, not examples: a literal example number here would trip this very scan.
PHONE = re.compile(
    # North American: NNN-NNN-NNNN, (NNN) NNN-NNNN, +1 NNN NNN NNNN
    r"(?<![\w.-])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?![\w-])"
    # Mobile numbers of the form 09NN-NNN-NNN, with or without separators
    r"|(?<![\w-])09\d{2}[\s-]?\d{3}[\s-]?\d{3}(?![\w-])"
    # Other international forms: +CC area local, separated by spaces or dashes
    r"|(?<![\w+])\+\d{1,3}[\s-]\d{1,4}[\s-]\d{3,4}[\s-]?\d{3,4}(?![\w-])"
)

HOME_PATH = re.compile(
    r"(?i)\b[a-z]:[\\/]+users[\\/]+(?!public\b|default\b)[^\\/\s\"'`<>]+"
    r"|(?<![\w.])/(?:Users|home)/(?!runner\b)[^/\s\"'`<>]+"
)

LINKEDIN_PROFILE = re.compile(r"(?i)linkedin\.com/in/[\w%-]+")

URL_HOST = re.compile(r"(?i)https?://([^/\s)\"'<>`\]]+)")
ALLOWED_HOSTS = {
    "github.com", "img.shields.io", "example.com", "example.org", "example.net",
    "docs.python.org", "pypi.org", "opensource.org", "localhost", "claude.com",
}

# Paths that must never be tracked, whatever they contain.
PRIVATE_DIRS = {"profiles", "resumes", "applications", "data", "interviews",
                "logs", "reports", "browser"}
PRIVATE_SUFFIXES = {".pdf", ".docx", ".doc", ".xlsx", ".odt", ".pages", ".rtf"}
PRIVATE_NAMES = re.compile(r"(?i)^(handoff.*\.md|experience_bank\.yaml|.*\.bak-.*|\.env.*)$")

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "build", "dist"}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    detail: str

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}: {self.kind} - {self.detail}"


def _mask(value: str) -> str:
    """Enough to find the spot, not enough to republish it in a CI log."""
    return value[:2] + "…" if len(value) > 2 else "…"


# --- denylist ---------------------------------------------------------------

def hash_term(term: str) -> str:
    return hashlib.sha256((SALT + term).encode("utf-8")).hexdigest()


def tokens(text: str) -> list[str]:
    return TOKEN.findall(unicodedata.normalize("NFKC", text).lower())


def normalize_term(term: str) -> str:
    """'Zebracorn-Industries' -> 'zebracorn industries'; CJK is kept as one run."""
    toks = tokens(term)
    if any(re.match(rf"[{CJK}]", t) for t in toks):
        joined = "".join(t for t in toks if re.match(rf"[{CJK}]", t))
        if not CJK_MIN <= len(joined) <= CJK_MAX:
            raise ValueError(f"CJK term must be {CJK_MIN}-{CJK_MAX} characters")
        return joined
    if not 1 <= len(toks) <= MAX_WORDS:
        raise ValueError(f"term must be 1-{MAX_WORDS} words")
    return " ".join(toks)


def phrase_hashes(text: str) -> set[str]:
    """Hashes of every phrase the denylist could name: 1-4 word runs, CJK substrings."""
    out: set[str] = set()
    words: list[str] = []
    for tok in tokens(text):
        if re.match(rf"[{CJK}]", tok):
            for i in range(len(tok)):
                for j in range(i + CJK_MIN, min(len(tok), i + CJK_MAX) + 1):
                    out.add(hash_term(tok[i:j]))
        else:
            words.append(tok)
    for i in range(len(words)):
        for n in range(1, MAX_WORDS + 1):
            if i + n <= len(words):
                out.add(hash_term(" ".join(words[i:i + n])))
    return out


def load_denylist(path: Path = DENYLIST) -> set[str]:
    if not path.exists():
        return set()
    return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")}


# --- scanning ---------------------------------------------------------------

def private_path(rel: str) -> str | None:
    """Why this path may not be tracked, or None if it may."""
    p = PurePosixPath(rel.replace("\\", "/"))
    if p.parts and p.parts[0] in PRIVATE_DIRS:
        return f"lives under {p.parts[0]}/, which holds private data"
    if p.suffix.lower() in PRIVATE_SUFFIXES:
        return f"{p.suffix} documents are never committed"
    if PRIVATE_NAMES.match(p.name):
        return "file name reserved for private data"
    return None


def scan_text(text: str, rel: str, denylist: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for no, line in enumerate(text.splitlines(), start=1):
        for m in EMAIL.finditer(line):
            if m.group(1).lower() not in ALLOWED_EMAIL_DOMAINS:
                findings.append(Finding(rel, no, "email address", _mask(m.group(0))))
        for m in PHONE.finditer(line):
            findings.append(Finding(rel, no, "phone number", _mask(m.group(0))))
        for m in HOME_PATH.finditer(line):
            findings.append(Finding(rel, no, "home-directory path", _mask(m.group(0))))
        for m in LINKEDIN_PROFILE.finditer(line):
            findings.append(Finding(rel, no, "LinkedIn profile URL", _mask(m.group(0))))
        for m in URL_HOST.finditer(line):
            host = m.group(1).lower().split(":")[0]
            if host not in ALLOWED_HOSTS:
                findings.append(Finding(rel, no, "link to unlisted host",
                                        f"{host} (add to ALLOWED_HOSTS if intended)"))
        if denylist:
            hits = phrase_hashes(line) & denylist
            for h in sorted(hits):
                findings.append(Finding(rel, no, "denylisted term", f"hash {h[:12]}"))
    return findings


def repo_files(root: Path = ROOT) -> list[str]:
    """Tracked files plus untracked ones git would add; a plain walk outside git."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root, capture_output=True, text=True, check=True, encoding="utf-8")
        files = [f for f in out.stdout.splitlines() if f and (root / f).is_file()]
        if files:
            return sorted(set(files))
    except (OSError, subprocess.CalledProcessError):
        pass
    return sorted(
        p.relative_to(root).as_posix() for p in root.rglob("*")
        if p.is_file() and not SKIP_DIRS & set(p.relative_to(root).parts)
        and not p.name.endswith(".egg-info")
        and not any(part.endswith(".egg-info") for part in p.relative_to(root).parts)
    )


def staged_files(root: Path = ROOT) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=root, capture_output=True, text=True, check=True, encoding="utf-8")
    return [f for f in out.stdout.splitlines() if f]


def _read(root: Path, rel: str, staged: bool) -> str | None:
    if staged:
        out = subprocess.run(["git", "show", f":{rel}"], cwd=root, capture_output=True)
        data = out.stdout
    else:
        data = (root / rel).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None                       # binary: judged by its path alone


def scan(root: Path = ROOT, files: list[str] | None = None, *, staged: bool = False,
         denylist: set[str] | None = None) -> list[Finding]:
    denylist = load_denylist() if denylist is None else denylist
    findings: list[Finding] = []
    for rel in files if files is not None else repo_files(root):
        reason = private_path(rel)
        if reason:
            findings.append(Finding(rel, 0, "private file", reason))
            continue
        if rel == DENYLIST.relative_to(ROOT).as_posix():
            continue                      # hashes only; its format has its own test
        text = _read(root, rel, staged)
        if text is not None:
            findings.extend(scan_text(text, rel, denylist))
    return findings


def build_denylist(terms_file: Path, out: Path = DENYLIST) -> int:
    """Hash a plaintext term list into the denylist. The plaintext never enters the repo."""
    terms_file = terms_file.resolve()
    if terms_file.is_relative_to(ROOT):
        raise ValueError(
            f"{terms_file} is inside the repository. Keep the plaintext list "
            "somewhere git will never see it.")
    hashes = set()
    for raw in terms_file.read_text(encoding="utf-8").splitlines():
        term = raw.split("#", 1)[0].strip()
        if term:
            hashes.add(hash_term(normalize_term(term)))
    out.write_text(
        "# Salted SHA-256 of terms that must never appear in this repository.\n"
        "# Generated by tools/privacy_scan.py --hash-terms. Do not edit by hand.\n"
        + "".join(f"{h}\n" for h in sorted(hashes)),
        encoding="utf-8", newline="\n")
    return len(hashes)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--staged", action="store_true", help="scan staged files only")
    ap.add_argument("--hash-terms", type=Path, metavar="FILE",
                    help="rebuild the hashed denylist from a plaintext list")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    if args.hash_terms:
        n = build_denylist(args.hash_terms)
        print(f"wrote {n} hashes to {DENYLIST.relative_to(ROOT)}")
        return 0

    files = staged_files() if args.staged else None
    findings = scan(files=files, staged=args.staged)
    for f in findings:
        print(f)
    print(f"privacy scan: {len(findings)} finding(s). {'BLOCKED.' if findings else 'OK.'}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
