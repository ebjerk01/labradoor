#!/usr/bin/env bash
# Labradoor installer for Proxmox VE: creates an unprivileged Debian 13 container, installs the newest signed Labradoor
# release in it and prints the one-time link that creates the owner account.  Run it as root on a Proxmox VE host:
#
#   bash -c "$(curl -fsSL <release server>/install.sh)"                       # asks a few questions
#   curl -fsSL <release server>/install.sh | bash -s -- --yes [options]       # unattended, defaults + options
#
# Everything is verified before it runs: the release index and the release are OpenSSH-signed (ssh-keygen -Y verify)
# with the key pinned below, the tarball's sha256 must match the signed index, and every file must match the
# release's MANIFEST. docs/install.md explains the options, updates, rollback and uninstalling.
set -euo pipefail
{ # one block: bash reads the whole script before running any of it (safe with curl | bash)

# The key Labradoor releases are signed with (deploy/release.pub). Not a secret.
RELEASE_PUB="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMq3EylNEDXmZnneZJasuRVUyQ0etsBqQZh3u/4+94rH labradoor-release"
# Where the signed release index lives (empty until releases are published: pass --index or --release-url/--release-file)
DEFAULT_INDEX=""
TAG="labradoor"
ME="install.sh"   # how the hints below name this script (it may come from a pipe)

usage() {
  cat <<'EOF'
Labradoor installer for Proxmox VE (run as root on the Proxmox host)

  install.sh [options]                      create a container and install Labradoor in it
  install.sh --uninstall --ctid ID [--yes]  stop and destroy a container this installer created

Container (asked interactively unless --yes; defaults in brackets):
  --ctid ID              container id [next free id]
  --hostname NAME        [labradoor]
  --storage STORAGE      storage for the root disk [local-lvm, local-zfs or the first one that holds containers]
  --disk GB              root disk size [4]
  --bridge BRIDGE        network bridge [vmbr0]
  --vlan TAG             VLAN tag on the bridge [none]
  --ip dhcp|CIDR         [dhcp]; a static address also needs --gateway
  --gateway IP           default gateway for a static address
  --cores N              [1]
  --memory MB            [512]
  --pool POOL            Proxmox resource pool [none]
  --template-storage S   where the Debian 13 template is kept [local]
  --ssh-key FILE         public key(s) for root's authorized_keys in the container [none: use 'pct enter ID']

Release (verified with the pinned signing key before anything runs):
  --index URL            signed release index [$LAB_RELEASE_INDEX, else the built-in default]
  --version V            install this version from the index [the newest]
  --release-url URL      install this release tarball (URL.sig must sit next to it) instead of using an index
  --release-file PATH    install a local tarball (PATH.sig next to it), e.g. for offline installs
  --release-pub FILE     verify with this public key instead of the pinned one (forks, testing)
  --allow-http           allow plain http:// to a LAN address (testing a local release server only); also lets
                         the installed copy update from that server
  --public-url URL       the address people will open [http://<container ip>:8100]; set https://… when you put
                         a reverse proxy in front (docs/install.md)

  --trust-labradoor-modules
                         trust modules published by the Labradoor project (the key that signs its releases), so its
                         module catalog can be installed from Settings → Modules [asked on a fresh install; no with --yes]
  --reinstall            install the release again into an existing Labradoor container
  --yes, -y              no questions: defaults + options
  --help
EOF
}

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mWARNING:\033[0m %s\n' "$*" >&2; }
die() { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

CTID="${LAB_CTID:-}" HOSTNAME_="${LAB_HOSTNAME:-labradoor}" STORAGE="${LAB_STORAGE:-}" DISK=4 BRIDGE="${LAB_BRIDGE:-vmbr0}"
VLAN="" IP="${LAB_IP:-dhcp}" GW="" CORES=1 MEMORY=512 POOL="" TSTORAGE=local SSH_KEY=""
INDEX="${LAB_RELEASE_INDEX:-$DEFAULT_INDEX}" VERSION="" RELEASE_URL="" RELEASE_FILE="" PUBFILE=""
ALLOW_HTTP="${LAB_INSTALL_ALLOW_HTTP:-0}" PUBLIC_URL="" PUBLIC_URL_GIVEN=0 INDEX_GIVEN=0 REINSTALL=0 YES=0 UNINSTALL=0 TRUST_MODULES=0
need_arg() { [ $# -ge 2 ] && [ -n "$2" ] || die "$1 needs a value (see --help)"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --ctid) need_arg "$@"; CTID="$2"; shift 2 ;;
    --hostname) need_arg "$@"; HOSTNAME_="$2"; shift 2 ;;
    --storage) need_arg "$@"; STORAGE="$2"; shift 2 ;;
    --disk) need_arg "$@"; DISK="$2"; shift 2 ;;
    --bridge) need_arg "$@"; BRIDGE="$2"; shift 2 ;;
    --vlan) need_arg "$@"; VLAN="$2"; shift 2 ;;
    --ip) need_arg "$@"; IP="$2"; shift 2 ;;
    --gateway) need_arg "$@"; GW="$2"; shift 2 ;;
    --cores) need_arg "$@"; CORES="$2"; shift 2 ;;
    --memory) need_arg "$@"; MEMORY="$2"; shift 2 ;;
    --pool) need_arg "$@"; POOL="$2"; shift 2 ;;
    --template-storage) need_arg "$@"; TSTORAGE="$2"; shift 2 ;;
    --ssh-key) need_arg "$@"; SSH_KEY="$2"; shift 2 ;;
    --index) need_arg "$@"; INDEX="$2"; INDEX_GIVEN=1; shift 2 ;;
    --version) need_arg "$@"; VERSION="$2"; shift 2 ;;
    --release-url) need_arg "$@"; RELEASE_URL="$2"; shift 2 ;;
    --release-file) need_arg "$@"; RELEASE_FILE="$2"; shift 2 ;;
    --release-pub) need_arg "$@"; PUBFILE="$2"; shift 2 ;;
    --allow-http) ALLOW_HTTP=1; shift ;;
    --public-url) need_arg "$@"; PUBLIC_URL="${2%/}"; PUBLIC_URL_GIVEN=1; shift 2 ;;
    --trust-labradoor-modules) TRUST_MODULES=1; shift ;;
    --reinstall) REINSTALL=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --yes|-y) YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

# --- questions (from the terminal even when the script itself comes from a pipe) -------------------------------------
TTY=""
if [ "$YES" != 1 ] && { exec 3</dev/tty; } 2>/dev/null; then TTY=1; fi
ask() {  # ask VAR "question" — keeps the current value as the default
  local var="$1" q="$2" cur="${!1}" ans=""
  [ -n "$TTY" ] || return 0
  read -r -u 3 -p "$q [${cur:-none}]: " ans || true
  [ -z "$ans" ] || printf -v "$var" '%s' "$ans"
}
confirm() {  # confirm "question" → 0 yes
  [ "$YES" = 1 ] && return 0
  [ -n "$TTY" ] || die "no terminal to confirm on: re-run with --yes"
  local ans=""; read -r -u 3 -p "$1 [y/N]: " ans || true
  case "$ans" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# --- checks ----------------------------------------------------------------------------------------------------------
[ "$(id -u)" = 0 ] || die "run as root on the Proxmox VE host"
if ! { [ -d /etc/pve ] && command -v pct >/dev/null && command -v pveam >/dev/null && command -v pvesh >/dev/null; }; then
  die "this is not a Proxmox VE host (no pct/pveam/pvesh, no /etc/pve)"
fi
for t in curl ssh-keygen sha256sum python3 tar; do command -v "$t" >/dev/null || die "missing on this host: $t"; done

is_ours() { pct config "$1" 2>/dev/null | grep -Eq "^tags:.*(^|[ ,;])${TAG}([ ,;]|$)"; }
ct_status() { pct status "$1" 2>/dev/null | awk '{print $2}'; }

# --- uninstall -------------------------------------------------------------------------------------------------------
if [ "$UNINSTALL" = 1 ]; then
  [ -n "$CTID" ] || die "--uninstall needs --ctid ID"
  pct config "$CTID" >/dev/null 2>&1 || die "there is no container $CTID on this node"
  is_ours "$CTID" || die "container $CTID was not created by this installer (no '$TAG' tag): not touching it"
  say "container $CTID: $(pct config "$CTID" | sed -n 's/^hostname: //p') ($(ct_status "$CTID"))"
  if [ "$YES" != 1 ]; then
    [ -n "$TTY" ] || die "no terminal to confirm on: re-run with --yes"
    read -r -u 3 -p "This DESTROYS container $CTID and all its data (accounts, settings, module secrets). Type the id to confirm: " ans || true
    [ "${ans:-}" = "$CTID" ] || die "not confirmed: nothing done"
  fi
  [ "$(ct_status "$CTID")" = running ] && { say "stopping $CTID"; pct stop "$CTID"; }
  say "destroying $CTID"
  pct destroy "$CTID" --purge 1 --destroy-unreferenced-disks 1
  say "done: container $CTID is gone (the Debian template stays in its storage for the next install)"
  exit 0
fi

# --- settings --------------------------------------------------------------------------------------------------------
# a re-run without --ctid: the Labradoor container on this node (by its tag) is the default, not a second installation
EXISTING=""
if [ -z "$CTID" ]; then
  OURS=()
  for id in $(pct list 2>/dev/null | awk 'NR > 1 {print $1}'); do if is_ours "$id"; then OURS+=("$id"); fi; done
  if [ "${#OURS[@]}" -eq 1 ]; then
    CTID="${OURS[0]}"; EXISTING="$CTID"
    say "found the Labradoor container $CTID on this node: using it (--ctid ID with a new id makes a second installation)"
  elif [ "${#OURS[@]}" -gt 1 ]; then
    [ -n "$TTY" ] || die "several Labradoor containers on this node (${OURS[*]}): pass --ctid ID"
    say "Labradoor containers on this node: ${OURS[*]} (type one of them to re-run the installer for it)"
  fi
fi
[ -n "$CTID" ] || CTID="$(pvesh get /cluster/nextid)"
if [ -z "$STORAGE" ]; then
  avail="$(pvesm status -content rootdir 2>/dev/null | awk 'NR>1 && $3=="active" {print $1}')"
  for s in local-lvm local-zfs; do if grep -qx "$s" <<<"$avail"; then STORAGE="$s"; break; fi; done
  [ -n "$STORAGE" ] || STORAGE="$(head -n 1 <<<"$avail")"
fi
if [ -n "$TTY" ]; then
  say "Labradoor: a few questions (Enter keeps the default)"
  ask CTID "container id${EXISTING:+ (Enter: the existing Labradoor container)}"
  if ! pct config "$CTID" >/dev/null 2>&1; then  # only a new container needs the rest
    ask HOSTNAME_ "hostname"; ask STORAGE "storage"; ask DISK "disk (GB)"; ask BRIDGE "bridge"
    ask VLAN "VLAN tag (empty: none)"; ask IP "IP address (dhcp or CIDR like 192.168.1.50/24)"
    if [ "$IP" != dhcp ]; then ask GW "gateway"; fi
    ask CORES "cores"; ask MEMORY "memory (MB)"
  fi
fi
[[ "$CTID" =~ ^[1-9][0-9]{2,8}$ ]] || die "container id: a number (100 or more)"
[[ "$HOSTNAME_" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$ ]] || die "hostname: letters, digits and -"
[[ "$DISK" =~ ^[1-9][0-9]{0,4}$ ]] || die "disk: whole GB"
[[ "$CORES" =~ ^[1-9][0-9]{0,2}$ ]] || die "cores: a number"
[[ "$MEMORY" =~ ^[1-9][0-9]{2,6}$ ]] || die "memory: MB (256 or more)"
[ -z "$VLAN" ] || [[ "$VLAN" =~ ^[1-9][0-9]{0,3}$ ]] || die "VLAN: 1-4094"
[ -n "$STORAGE" ] || die "no storage for containers found: pass --storage"
pvesm status -storage "$STORAGE" >/dev/null 2>&1 || die "no storage $STORAGE on this node"
ip link show "$BRIDGE" >/dev/null 2>&1 || die "no bridge $BRIDGE on this node"
if [ "$IP" != dhcp ]; then
  [[ "$IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$ ]] || die "IP: dhcp or an IPv4 address with prefix, e.g. 192.168.1.50/24"
  [ -n "$GW" ] || die "a static IP needs --gateway"
fi
[ -z "$SSH_KEY" ] || [ -f "$SSH_KEY" ] || die "--ssh-key: no file $SSH_KEY"
[ -z "$POOL" ] || pvesh get "/pools/$POOL" >/dev/null 2>&1 || die "no resource pool $POOL"

WORK="$(mktemp -d /tmp/labradoor-install.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
CT_PATH="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"   # pct exec has no /usr/local
in_ct() { pct exec "$CTID" -- env "$CT_PATH" "$@" </dev/null; }

# an existing container of ours with Labradoor in it: nothing to download unless --reinstall (a re-run only applies
# --public-url / --index / --allow-http and prints the state)
INSTALLED=0
if pct config "$CTID" >/dev/null 2>&1; then
  is_ours "$CTID" || die "container $CTID exists and was not created by this installer: choose another --ctid"
  [ "$(ct_status "$CTID")" = running ] || { say "starting $CTID"; pct start "$CTID"; sleep 3; }
  if in_ct test -e /opt/lab/VERSION; then INSTALLED=1; fi
fi

# --- the release: download + verify BEFORE touching anything --------------------------------------------------------
if [ -n "$PUBFILE" ]; then cp "$PUBFILE" "$WORK/release.pub"; else echo "$RELEASE_PUB" > "$WORK/release.pub"; fi
grep -v '^#' "$WORK/release.pub" | awk 'NF {print "labradoor-release namespaces=\"labradoor-release\" " $1 " " $2}' > "$WORK/allowed_signers"
[ -s "$WORK/allowed_signers" ] || die "no public key in ${PUBFILE:-the pinned key}"
verify() {  # verify FILE SIG
  ssh-keygen -Y verify -f "$WORK/allowed_signers" -I labradoor-release -n labradoor-release -s "$2" < "$1" >/dev/null 2>&1
}
url_ok() {  # https:// always; http:// only with --allow-http and only to a private address
  case "$1" in
    https://*) return 0 ;;
    http://*) [ "$ALLOW_HTTP" = 1 ] || die "only https:// release URLs are allowed (--allow-http for a LAN test server): $1"
      python3 -I - "$1" <<'PY' || die "http:// is only allowed to a LAN address: $1"
import ipaddress, socket, sys, urllib.parse
h = urllib.parse.urlsplit(sys.argv[1]).hostname
a = {i[4][0] for i in socket.getaddrinfo(h, None)}
sys.exit(0 if a and all((lambda x: x.is_private or x.is_loopback)(ipaddress.ip_address(x)) for x in a) else 1)
PY
      ;;
    *) die "not an http(s) URL: $1" ;;
  esac
}
fetch() {  # fetch URL FILE MAXBYTES
  url_ok "$1"
  local proto="=https"; [ "$ALLOW_HTTP" = 1 ] && proto="=http,https"
  curl -fsSL --proto "$proto" --proto-redir "$proto" --max-redirs 5 --retry 2 --connect-timeout 15 \
    --max-filesize "$3" -A labradoor-installer -o "$2" "$1" || die "download failed: $1"
}

if [ "$INSTALLED" = 1 ] && [ "$REINSTALL" != 1 ]; then
  VERSION="$(in_ct cat /opt/lab/VERSION)"; SOURCE="(installed)"
elif [ -n "$RELEASE_FILE" ]; then
  [ -f "$RELEASE_FILE" ] && [ -f "$RELEASE_FILE.sig" ] || die "--release-file needs FILE and FILE.sig"
  cp "$RELEASE_FILE" "$WORK/release.tar.gz"; cp "$RELEASE_FILE.sig" "$WORK/release.tar.gz.sig"
  SOURCE="$RELEASE_FILE"
elif [ -n "$RELEASE_URL" ]; then
  fetch "$RELEASE_URL" "$WORK/release.tar.gz" 268435456; fetch "$RELEASE_URL.sig" "$WORK/release.tar.gz.sig" 65536
  SOURCE="$RELEASE_URL"
elif [ -n "$INDEX" ]; then
  say "release index: $INDEX"
  fetch "$INDEX" "$WORK/index.json" 1048576; fetch "$INDEX.sig" "$WORK/index.json.sig" 65536
  verify "$WORK/index.json" "$WORK/index.json.sig" || die "the release index signature does NOT verify: refusing"
  # → version, sha256, tarball URL, signature URL (relative URLs resolve against the index URL)
  PICK="$(python3 -I - "$WORK/index.json" "$INDEX" "$VERSION" <<'PY'
import json, re, sys, urllib.parse
path, base, want = sys.argv[1:]
SV = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?$")
def key(v):
    m = SV.match(v)
    pre = m.group(4)
    ids = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split(".")) if pre else ()
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if pre else 1, ids)
doc = json.load(open(path))
rel = [e for e in doc.get("releases", []) if isinstance(e, dict) and SV.match(str(e.get("version", "")))
       and re.fullmatch(r"[0-9a-f]{64}", str(e.get("sha256", ""))) and isinstance(e.get("url"), str)]
if want:
    rel = [e for e in rel if e["version"] == want]
if not rel:
    sys.exit(f"no {'release ' + want if want else 'release'} in the index")
e = max(rel, key=lambda e: key(e["version"]))
url = urllib.parse.urljoin(base, e["url"])
sig = urllib.parse.urljoin(base, e["sig"]) if e.get("sig") else url + ".sig"
print(e["version"], e["sha256"], url, sig)
PY
)" || die "release index: ${PICK:-unreadable}"
  read -r IDX_VER IDX_SHA TAR_URL SIG_URL <<<"$PICK"
  fetch "$TAR_URL" "$WORK/release.tar.gz" 268435456; fetch "$SIG_URL" "$WORK/release.tar.gz.sig" 65536
  [ "$(sha256sum "$WORK/release.tar.gz" | cut -d' ' -f1)" = "$IDX_SHA" ] || die "sha256 of $TAR_URL does not match the signed index: refusing"
  VERSION="${VERSION:-$IDX_VER}"
  SOURCE="$TAR_URL"
else
  die "no release source: pass --index URL (or set LAB_RELEASE_INDEX), --release-url URL or --release-file PATH"
fi
if [ "$SOURCE" != "(installed)" ]; then
  verify "$WORK/release.tar.gz" "$WORK/release.tar.gz.sig" || die "the release signature does NOT verify with ${PUBFILE:-the pinned key}: refusing"
  TOP="$(tar -tzf "$WORK/release.tar.gz" | awk -F/ 'NR == 1 {print $1}')"   # awk reads it all: no SIGPIPE under pipefail
  [[ "$TOP" =~ ^labradoor-[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || die "not a Labradoor release tarball ($TOP)"
  REL_VER="${TOP#labradoor-}"
  [ -z "$VERSION" ] || [ "$VERSION" = "$REL_VER" ] || die "the tarball is $REL_VER, not $VERSION"
  VERSION="$REL_VER"
  say "release $VERSION: signature good ($SOURCE)"
fi

# --- the container ---------------------------------------------------------------------------------------------------
NEW_CT=0
if pct config "$CTID" >/dev/null 2>&1; then
  say "container $CTID exists (created by this installer): using it"
else
  pvesh get /cluster/resources --type vm --output-format json 2>/dev/null | python3 -I -c \
    'import json,sys; sys.exit(1 if any(str(r.get("vmid"))==sys.argv[1] for r in json.load(sys.stdin)) else 0)' "$CTID" ||
    die "id $CTID is used by another guest in the cluster"
  NET="name=eth0,bridge=$BRIDGE,ip=$IP${GW:+,gw=$GW}${VLAN:+,tag=$VLAN}"
  echo
  echo "  container $CTID '$HOSTNAME_': Debian 13, unprivileged, $CORES core(s), $MEMORY MB, ${DISK} GB on $STORAGE"
  echo "  network $NET${POOL:+, pool $POOL}; starts at boot; Labradoor $VERSION"
  echo
  confirm "Create it?" || die "cancelled: nothing created"
  T="$(pveam list "$TSTORAGE" 2>/dev/null | awk '{print $1}' | grep -E 'debian-13-standard_.*_amd64\.tar\.(zst|gz|xz)$' | sort -V | tail -n 1 || true)"
  if [ -z "$T" ]; then
    say "downloading the Debian 13 template to $TSTORAGE"
    pveam update >/dev/null || warn "pveam update failed (trying the cached list)"
    NAME="$(pveam available --section system | awk '{print $2}' | grep -E '^debian-13-standard_.*_amd64' | sort -V | tail -n 1)"
    [ -n "$NAME" ] || die "no Debian 13 template available from pveam"
    pveam download "$TSTORAGE" "$NAME"
    T="$TSTORAGE:vztmpl/$NAME"
  fi
  say "creating container $CTID from $T"
  args=(--hostname "$HOSTNAME_" --cores "$CORES" --memory "$MEMORY" --swap 512 --rootfs "$STORAGE:$DISK"
        --net0 "$NET" --unprivileged 1 --features nesting=0 --onboot 1 --ostype debian --tags "$TAG"
        --description "Labradoor (created by the Labradoor installer). Updates: Settings → Updates or 'lab-admin update'.")
  [ -z "$POOL" ] || args+=(--pool "$POOL")
  [ -z "$SSH_KEY" ] || args+=(--ssh-public-keys "$SSH_KEY")
  pct create "$CTID" "$T" "${args[@]}" >/dev/null
  say "(Proxmox may warn about systemd and nesting when the container starts: expected, Labradoor runs without nesting on purpose)"
  NEW_CT=1
fi
trap 'rm -rf "$WORK"; [ "$NEW_CT" = 1 ] && echo "Container $CTID was left as it is for a look; remove it with: $ME --uninstall --ctid $CTID" >&2' EXIT
[ "$(ct_status "$CTID")" = running ] || { say "starting $CTID"; pct start "$CTID"; }
CTIP=""
for _ in $(seq 1 60); do
  CTIP="$(in_ct ip -4 -o addr show dev eth0 scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n 1 || true)"
  [ -n "$CTIP" ] && break; sleep 2
done
[ -n "$CTIP" ] || die "container $CTID got no IPv4 address on eth0 (DHCP on $BRIDGE${VLAN:+ VLAN $VLAN}?)"
say "container $CTID is up at $CTIP"
NEW_IP_DHCP=0; if pct config "$CTID" | grep -Eq '^net0:.*ip=dhcp'; then NEW_IP_DHCP=1; fi

FRESH=0
if [ "$INSTALLED" = 1 ] && [ "$REINSTALL" != 1 ]; then
  say "Labradoor $VERSION is installed already (--reinstall installs a release again; updates: Settings → ~/updates)"
else
  [ "$INSTALLED" = 1 ] || FRESH=1
  say "installing packages (python3, ca-certificates, nftables, curl, openssh-client)"
  for _ in $(seq 1 15); do in_ct getent hosts deb.debian.org >/dev/null 2>&1 && break; sleep 2; done
  in_ct env DEBIAN_FRONTEND=noninteractive apt-get update -q >"$WORK/apt.log" 2>&1 || { tail -n 20 "$WORK/apt.log"; die "apt-get update failed in the container (internet/DNS?)"; }
  in_ct env DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends \
    python3 ca-certificates nftables curl openssh-client >>"$WORK/apt.log" 2>&1 || { tail -n 20 "$WORK/apt.log"; die "apt-get install failed"; }
  # systemd ≥ 257 in an unprivileged container without nesting can't make these mounts; they fail at every boot and
  # leave the container "degraded" though nothing needs them (/tmp stays on the root disk)
  for u in dev-mqueue.mount run-lock.mount tmp.mount; do
    if in_ct systemctl is-failed -q "$u"; then in_ct systemctl mask -q "$u"; fi
  done
  in_ct systemctl reset-failed
  say "installing Labradoor $VERSION"
  pct push "$CTID" "$WORK/release.tar.gz" /root/labradoor-release.tar.gz
  in_ct sh -c 'rm -rf /root/labradoor-release && mkdir -m 700 /root/labradoor-release && tar -xzf /root/labradoor-release.tar.gz -C /root/labradoor-release && rm -f /root/labradoor-release.tar.gz'
  TREE="/root/labradoor-release/labradoor-$VERSION"
  in_ct python3 -I "$TREE/deploy/lab-update-helper" verify-tree "$TREE" "$VERSION" || die "the release does not match its MANIFEST: refusing"
  # LAB_SKIP_SETUP_LINK: the first-run link is minted once, below, after the public address is set
  if ! in_ct env LAB_SKIP_SETUP_LINK=1 flock -w 900 /run/lab-deploy.lock sh "$TREE/deploy/install.sh" >"$WORK/install.log" 2>&1; then
    tail -n 40 "$WORK/install.log"; die "deploy/install.sh failed in the container"
  fi
  grep -E '^release .* live' "$WORK/install.log" || true
  in_ct rm -rf /root/labradoor-release
fi

# --- this installation's settings (only what the installer knows; everything else: Settings in the UI) --------------
# a re-run keeps what the owner set, unless --public-url / --index say otherwise
if [ -z "$PUBLIC_URL" ]; then
  PUBLIC_URL="$(in_ct sed -n 's/^LAB_PUBLIC_URL=//p' /etc/lab/lab.env 2>/dev/null | tail -n 1)"
  if [ "$FRESH" = 1 ] || [ -z "$PUBLIC_URL" ] || [ "$PUBLIC_URL" = "https://labradoor.example.com" ]; then
    PUBLIC_URL="http://$CTIP:8100"; PUBLIC_URL_GIVEN=1
  fi
fi
SECURE=1; case "$PUBLIC_URL" in http://*) SECURE=0 ;; esac
set_env() {  # set_env FILE KEY VALUE (replace or append; keeps the file's owner and mode)
  pct exec "$CTID" -- python3 -I - "$@" <<'PY'
import os, sys
path, key, value = sys.argv[1:]
lines = open(path).read().splitlines() if os.path.exists(path) else []
out, done = [], False
for ln in lines:
    if ln.startswith(key + "="):
        if not done:
            out.append(f"{key}={value}")
        done = True
    else:
        out.append(ln)
if not done:
    out.append(f"{key}={value}")
with open(path, "r+" if os.path.exists(path) else "w") as f:
    f.write("\n".join(out) + "\n")
    f.truncate()
PY
}
in_ct test -f /etc/lab/lab.env || die "no /etc/lab/lab.env in the container (did deploy/install.sh run?)"
if [ "$PUBLIC_URL_GIVEN" = 1 ]; then
  set_env /etc/lab/lab.env LAB_PUBLIC_URL "$PUBLIC_URL"
  set_env /etc/lab/lab.env LAB_COOKIE_SECURE "$SECURE"
  say "public address set: $PUBLIC_URL"
fi
if [ -n "$INDEX" ] && { [ "$FRESH" = 1 ] || [ "$INDEX_GIVEN" = 1 ]; }; then
  set_env /etc/lab/lab.env LAB_RELEASE_INDEX "$INDEX"; say "release index set: $INDEX"
fi
if [ "$ALLOW_HTTP" = 1 ]; then
  in_ct sh -c 'umask 022; echo "LAB_UPDATE_ALLOW_HTTP=1" > /etc/lab/update.env'
  warn "plain http:// release servers on the LAN are allowed in this container (/etc/lab/update.env) — testing only"
fi
# module publishers: none by default (a publisher's module screens run in the owner's browser: docs/catalog.md)
if [ "$TRUST_MODULES" != 1 ] && [ "$FRESH" = 1 ] && [ -n "$TTY" ]; then
  echo "Modules from the Labradoor catalog run their screens in your browser with your rights."
  read -r -u 3 -p "Trust modules published by the Labradoor project (the key that signs its releases)? [y/N]: " ans || true
  case "$ans" in y|Y|yes|YES) TRUST_MODULES=1 ;; esac
fi
if [ "$TRUST_MODULES" = 1 ]; then
  in_ct lab-admin publisher add /etc/lab/release.pub --name labradoor >/dev/null || die "could not add the publisher labradoor"
  say "trusted module publisher: labradoor"
fi
in_ct systemctl restart lab
ok=0; for _ in $(seq 1 20); do if in_ct curl -fsS -o /dev/null http://127.0.0.1:8100/healthz 2>/dev/null; then ok=1; break; fi; sleep 1; done
[ "$ok" = 1 ] || die "the gateway does not answer in container $CTID (pct enter $CTID; journalctl -u lab)"
NEW_CT=0   # done: keep the container whatever happens below
LINK="$(in_ct lab-admin setup-link 2>/dev/null | grep -Eo 'https?://[^ ]+/setup#[^ ]+' || true)"

echo
say "Labradoor $(in_ct cat /opt/lab/VERSION) is running in container $CTID"
echo "  open:          $PUBLIC_URL"
if [ -n "$LINK" ]; then
  echo "  FIRST RUN — open this link within 1 hour to create the owner account (it works once):"
  echo
  echo "    $LINK"
  echo
  echo "  a new link: pct exec $CTID -- lab-admin setup-link"
else
  echo "  an owner exists already: log in"
fi
echo "  updates:       Settings → ~/updates (owner), or: pct exec $CTID -- lab-admin update"
echo "  uninstall:     run this installer again with --uninstall --ctid $CTID (asks you to type the id)"
if [ "$NEW_IP_DHCP" = 1 ]; then
  echo "  note: $CTIP came from DHCP: reserve it in your router (or use --ip); if it changes, re-run with --public-url"
fi
[ "$SECURE" = 1 ] || echo "  note: served over plain http — put it behind an HTTPS reverse proxy and re-run with --public-url https://… (docs/install.md)"
exit 0
}
