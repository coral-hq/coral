exec 2>/dev/null
set +x
# What a step's shell reaches. Each argument is <check>|<kind>|<target>|<expect>. It
# prints only <check>=<verdict>, <check>.names=<NAME,...> for an environment it read and,
# given a canary's digest, <check>.api_key and <check>.argv_api_key; never a value.
LC_ALL=C
export LC_ALL

# Verdicts: reachable, denied (EACCES/EPERM), hidden (ENOENT, or nothing there in this
# view), not_present, mismatch (read, but not the host's canary), unclassified.
classify() {
  case $1 in
    *"No such file or directory"*) echo hidden ;;
    *"Permission denied"* | *"Operation not permitted"*) echo denied ;;
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

# The credential-like names among NAME=... lines on stdin, comma-separated, or none.
sensitive_names() {
  sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' | while read -r name; do
    case $name in
      OMNIGENT_RUNNER_*TOKEN* | OMNIGENT_RUNNER_TUNNEL_BINDING_TOKEN | \
        OMNIGENT_RUNNER_INITIAL_AUTH_TOKEN | *API_KEY* | HARNESS_CLAUDE_SDK_*)
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

# One connection, unix socket or HTTP, classified by its errno; never sends a credential.
CONNECT='
import socket, sys, urllib.error, urllib.request
kind, target = sys.argv[1], sys.argv[2]
def verdict(error):
    if isinstance(error, PermissionError):
        return "denied"
    if isinstance(error, (FileNotFoundError, socket.gaierror)):
        return "hidden"
    if kind == "http" and isinstance(error, ConnectionRefusedError):
        return "hidden"
    return "unclassified"
try:
    if kind == "socket":
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(5)
            client.connect(target)
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
    socket | http) verdict=$(python3 -I -c "$CONNECT" "$kind" "$target") ;;
    python) verdict=$(python3 -I -c 'print("reachable")') ;;
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
