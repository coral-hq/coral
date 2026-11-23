exec 2>/dev/null
set +x
# What a step's shell reaches. Each argument is <check>|<kind>|<target>|<expect>. It prints
# <check>=<verdict> and, never a value: <check>.names (an environment's credential-like
# names), <check>.read (a credential's read) and <check>.api_key / .argv_api_key (a canary).
LC_ALL=C
export LC_ALL

# Verdicts: reachable, denied (EACCES/EPERM/EROFS), hidden (ENOENT), not_present, mismatch
# (read, but not the canary or not this server's), refused (HTTP 401/403), minted (a minted
# JWT acts as the owner), unclassified.
classify() {
  case $1 in
    *"No such file or directory"*) echo hidden ;;
    *"Permission denied"* | *"Operation not permitted"* | *"Read-only file system"*) echo denied ;;
    *) echo unclassified ;;
  esac
}

digest() {
  if command -v sha256sum >/dev/null; then sha256sum; else shasum -a 256; fi | cut -d' ' -f1
}

# Shaped like a canary, made here and never printed: what a "self" read must find.
CONTROL=canary-$(printf 'probe-control-%s' "$$" | digest | cut -c1-32)
CONTROL_DIGEST=sha256:$(printf %s "$CONTROL" | digest)

# Whether stdin holds a canary-shaped value whose digest is $1; nothing is printed.
holds_canary() {
  for found in $(grep -o 'canary-[0-9a-f]\{32\}'); do
    if [ "sha256:$(printf %s "$found" | digest)" = "$1" ]; then return 0; fi
  done
  return 1
}

# The credential-like names among NAME=... lines on stdin, in any case, comma-separated,
# or none.
sensitive_names() {
  sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' | while read -r name; do
    case $(printf %s "$name" | tr '[:lower:]' '[:upper:]') in
      *TOKEN* | *SECRET* | *PASSWORD* | *PASSWD* | *CREDENTIAL* | *BEARER* | *API_KEY* | \
        *PRIVATE_KEY* | *COOKIE* | HARNESS_CLAUDE_SDK_*)
        echo "$name"
        ;;
    esac
  done | sort -u | paste -s -d, - | grep . || echo none
}

probe_file() {
  error=$(cat -- "$1" 2>&1 >/dev/null) || {
    classify "$error"
    return
  }
  case $2 in
    sha256:*) found=sha256:$(digest <"$1") ;;
    size:*) found=size:$(wc -c <"$1" | tr -d ' ') ;;
    *) found= ;;
  esac
  if [ "$found" = "$2" ]; then echo reachable; else echo mismatch; fi
}

# A canary token inside a larger file, compared by its digest.
probe_token() {
  error=$(cat -- "$1" 2>&1 >/dev/null) || {
    classify "$error"
    return
  }
  if holds_canary "$2" <"$1"; then echo reachable; else echo mismatch; fi
}

# Without /proc, a process's environment or command line through sysctl(KERN_PROCARGS2),
# the call behind ps eww: the read's verdict, then one line per entry. "self" is the reader.
READER='
import os, sys
import psutil
try:
    proc = psutil.Process(os.getpid() if sys.argv[2] == "self" else int(sys.argv[2]))
    if sys.argv[1] == "environ":
        lines = [name + "=" + value for name, value in proc.environ().items()]
    else:
        lines = proc.cmdline()
except psutil.AccessDenied:
    print("denied")
except psutil.NoSuchProcess:
    print("hidden")
else:
    print("reachable")
    for line in lines:
        print(line.replace("\n", " "))
'

# One /proc file ($1) of a process ($2); "self" is a shell holding CONTROL in both files.
proc_cat() {
  if [ "$2" = self ]; then
    PROBE_CONTROL_API_KEY=$CONTROL sh -c 'cat "/proc/$$/$1" || exit; :' "$CONTROL" "$1"
  else
    cat "/proc/$2/$1"
  fi
}

# A process's environ or cmdline ($1) by pid ($2): the read's verdict, then one line per entry.
read_process() {
  if [ -d /proc/self ]; then
    error=$(proc_cat "$1" "$2" 2>&1 >/dev/null) || {
      classify "$error"
      return
    }
    echo reachable
    proc_cat "$1" "$2" | tr '\n\0' ' \n'
  elif [ "$2" = self ]; then
    PROBE_CONTROL_API_KEY=$CONTROL python3 -I -c "$READER" "$1" self "$CONTROL"
  else
    python3 -I -c "$READER" "$1" "$2"
  fi
}

# reachable when a read ($1, $2) holds the canary whose digest is $3, else why not.
canary_verdict() {
  if [ "$1" != reachable ]; then
    echo "${1:-unclassified}"
  elif printf '%s\n' "$2" | holds_canary "$3"; then
    echo reachable
  else
    echo not_present
  fi
}

# An environment without PATH or HOME, or an empty command line, was not read: denied.
probe_process() {
  expect=$3
  if [ "$2" = self ]; then expect=$CONTROL_DIGEST; fi
  block=$(read_process environ "$2")
  verdict=$(printf '%s\n' "$block" | head -n 1)
  if [ "$verdict" = reachable ] && ! printf '%s\n' "$block" | grep -qE '^(PATH|HOME)='; then
    verdict=denied
  fi
  echo "$1=${verdict:-unclassified}"
  if [ "$verdict" = reachable ]; then
    echo "$1.names=$(printf '%s\n' "$block" | sensitive_names)"
  fi
  [ -n "$expect" ] || return 0
  echo "$1.api_key=$(canary_verdict "$verdict" "$block" "$expect")"
  block=$(read_process cmdline "$2")
  verdict=$(printf '%s\n' "$block" | head -n 1)
  if [ "$verdict" = reachable ] && [ -z "$(printf '%s\n' "$block" | sed 1d)" ]; then
    verdict=denied
  fi
  echo "$1.argv_api_key=$(canary_verdict "$verdict" "$block" "$expect")"
}

# One connection, unix socket (an @name is Linux's abstract namespace), TCP <host>:<port>
# or HTTP, classified by its errno; never sends a credential.
CONNECT='
import socket, sys, urllib.error, urllib.request
kind, target = sys.argv[1], sys.argv[2]
def verdict(error):
    if isinstance(error, PermissionError):
        return "denied"
    if isinstance(error, (FileNotFoundError, socket.gaierror)):
        return "hidden"
    # Nothing listens on the port, or no abstract socket has the name.
    if isinstance(error, ConnectionRefusedError) and (kind != "socket" or target[:1] == "@"):
        return "hidden"
    return "unclassified"
try:
    if kind == "socket":
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(5)
            client.connect("\0" + target[1:] if target.startswith("@") else target)
    elif kind == "tcp":
        host, _, port = target.rpartition(":")
        socket.create_connection((host, int(port)), timeout=5).close()
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            opener.open(target, timeout=5).close()
        except urllib.error.HTTPError:
            pass
except urllib.error.URLError as error:
    print(verdict(error.reason) if isinstance(error.reason, OSError) else "unclassified")
except OSError as error:
    print(verdict(error))
else:
    print("reachable")
'

# Uses a credential the step read (from stdin) once, never printed, and only on its own
# server: a stored entry keyed by that server's URL, or an environment whose RUNNER_SERVER_URL
# names it. Redirects are refused, so a credential never travels on to another server.
IDENTITY='
import hashlib, json, sys, urllib.error, urllib.request
mode, base, owner = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3]
class Unredirected(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Unredirected)
def status(url, headers, method="GET"):
    request = urllib.request.Request(
        url, headers=headers, method=method, data=b"" if method == "POST" else None
    )
    try:
        with opener.open(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""
def as_owner(token):
    code, _ = status(owner, {"Authorization": "Bearer " + token} if token else {})
    if 200 <= code < 300:
        return "reachable"
    return "refused" if code in (401, 403) else "unclassified"
def stored(entries):
    tokens = {
        key.rstrip("/"): entry["token"]
        for key, entry in entries.items()
        if isinstance(entry, dict) and isinstance(entry.get("token"), str) and entry["token"]
    }
    if not tokens:
        return "not_present"
    return as_owner(tokens[base]) if base in tokens else "mismatch"
def from_environ(lines):
    found = dict(line.partition("=")[::2] for line in lines if "=" in line)
    name = "OMNIGENT_RUNNER_" + ("TUNNEL_BINDING" if mode == "mint" else "INITIAL_AUTH") + "_TOKEN"
    token = found.get(name, "").strip()
    if not token:
        return "not_present"
    if found.get("RUNNER_SERVER_URL", "").strip().rstrip("/") != base:
        return "mismatch"
    if mode == "bearer":
        return as_owner(token)
    digest = hashlib.sha256(("omnigent-runner:" + token).encode()).hexdigest()
    url = base + "/v1/runners/runner_token_" + digest[:32] + "/token"
    code, body = status(url, {"X-Omnigent-Runner-Tunnel-Token": token}, "POST")
    if code in (401, 403):
        return "refused"
    jwt = json.loads(body).get("token") if code == 200 else None
    if not isinstance(jwt, str) or not jwt:
        return "unclassified"
    return "minted" if as_owner(jwt) == "reachable" else "refused"
try:
    if mode == "owner_http":
        print(as_owner(""))
    elif mode == "stored":
        print(stored(json.loads(sys.stdin.read())))
    else:
        print(from_environ(sys.stdin.read().splitlines()))
except (urllib.error.URLError, OSError) as error:
    reason = getattr(error, "reason", error)
    if isinstance(reason, ConnectionRefusedError):
        print("hidden")
    elif isinstance(reason, PermissionError):
        print("denied")
    else:
        print("unclassified")
except Exception:
    print("unclassified")
'

# mint or bearer ($2) for check $1 from process $3's environment, on server $4, owner
# route $5: the read's verdict as $1.read, then what the credential did.
identity_from_environ() {
  block=$(read_process environ "$3")
  read_verdict=$(printf '%s\n' "$block" | head -n 1)
  if [ "$read_verdict" = reachable ] && ! printf '%s\n' "$block" | grep -qE '^(PATH|HOME)='; then
    read_verdict=denied
  fi
  echo "$1.read=${read_verdict:-unclassified}"
  if [ "$read_verdict" = reachable ]; then
    verdict=$(printf '%s\n' "$block" | sed 1d | python3 -I -c "$IDENTITY" "$2" "$4" "$5")
  else
    verdict=$read_verdict
  fi
  echo "$1=${verdict:-unclassified}"
}

# The CLI's stored credentials ($2) for check $1: the read as $1.read, then whether the
# entry for server $3 acts as the owner on route $4.
probe_stored() {
  if error=$(cat -- "$2" 2>&1 >/dev/null); then
    read_verdict=reachable
  else
    read_verdict=$(classify "$error")
  fi
  echo "$1.read=$read_verdict"
  if [ "$read_verdict" = reachable ]; then
    verdict=$(python3 -I -c "$IDENTITY" stored "$3" "$4" <"$2")
  else
    verdict=$read_verdict
  fi
  echo "$1=${verdict:-unclassified}"
}

# A nested repository in a new directory ($1), one git takes as a repository, whose config
# names an fsmonitor hook the owner's git would run: reachable once written. Never writes
# into a path already there; removed again before the verdict is printed.
plant_repository() {
  error=$(
    {
      mkdir -- "$1/.git" "$1/.git/objects" "$1/.git/refs" &&
        hook=$(cd -- "$1" && pwd)/fsmonitor-hook &&
        printf 'ref: refs/heads/main\n' >"$1/.git/HEAD" &&
        printf '[core]\n\tfsmonitor = %s\n' "$hook" >"$1/.git/config" &&
        printf '#!/bin/sh\nexit 0\n' >"$hook" &&
        chmod +x "$hook"
    } 2>&1
  ) || {
    classify "$error"
    return
  }
  if grep -q 'fsmonitor = ' "$1/.git/config"; then echo reachable; else echo unclassified; fi
}

probe_plant() {
  error=$(mkdir -- "$1" 2>&1) || {
    classify "$error"
    return
  }
  verdict=$(plant_repository "$1")
  rm -rf -- "$1"
  echo "$verdict"
}

for argument in "$@"; do
  check=${argument%%|*}
  rest=${argument#*|}
  kind=${rest%%|*}
  rest=${rest#*|}
  target=${rest%%|*}
  expect=${rest#*|}
  case $kind in
    file) verdict=$(probe_file "$target" "$expect") ;;
    token) verdict=$(probe_token "$target" "$expect") ;;
    environ)
      probe_process "$check" "$target" "$expect"
      continue
      ;;
    socket | tcp | http) verdict=$(python3 -I -c "$CONNECT" "$kind" "$target") ;;
    python) verdict=$(python3 -I -c 'print("reachable")') ;;
    owner_http) verdict=$(python3 -I -c "$IDENTITY" owner_http "" "$target") ;;
    # For these the target is a pid or a file, and expect is <server base> <owner route>.
    mint | bearer)
      identity_from_environ "$check" "$kind" "$target" "${expect%% *}" "${expect#* }"
      continue
      ;;
    stored)
      probe_stored "$check" "$target" "${expect%% *}" "${expect#* }"
      continue
      ;;
    plant) verdict=$(probe_plant "$target") ;;
    shell)
      # The shell's own environment counts as read only when PATH is among its names.
      block=$(env -0 | tr '\n\0' ' \n')
      if ! printf '%s\n' "$block" | grep -q '^PATH='; then
        echo "$check=unclassified"
        continue
      fi
      names=$(printf '%s\n' "$block" | sensitive_names)
      if [ "$names" = none ]; then echo "$check=not_present"; else echo "$check=reachable"; fi
      echo "$check.names=$names"
      continue
      ;;
    *) verdict= ;;
  esac
  echo "$check=${verdict:-unclassified}"
done
