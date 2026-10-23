#!/bin/sh
set -e

# ============================================================================
#  Open Terminal — Hardened Entrypoint (Slim & Alpine)
# ============================================================================
#
#  This entrypoint is shared by both the slim (Debian) and Alpine images.
#  It handles:
#    1. Docker-secrets support (_FILE env vars)
#    2. Home directory permissions & dotfile seeding
#    3. Network egress filtering (iptables + dnsmasq whitelist)
#
#  What it does NOT do (by design):
#    ✘  No runtime apt/pip package installation
#    ✘  No Docker socket detection
#    ✘  No sudo — privilege drop uses gosu (Debian) or su-exec (Alpine)
#
# ============================================================================


# ── Helper: Docker-secrets _FILE resolution ────────────────────────────────
#
# Follows the convention from the official PostgreSQL image.
# If OPEN_TERMINAL_API_KEY_FILE is set, its contents become the key.
#
file_env() {
    local var="$1"
    local fileVar="${var}_FILE"
    local def="${2:-}"

    local val="$def"
    eval local currentVal="\${$var:-}"
    eval local fileVal="\${$fileVar:-}"
    eval local varIsSet="\${$var+set}"
    eval local fileIsSet="\${$fileVar+set}"

    if [ "$varIsSet" = "set" ] && [ "$fileIsSet" = "set" ]; then
        printf >&2 'error: both %s and %s are set (but are exclusive)\n' "$var" "$fileVar"
        exit 1
    fi

    if [ -n "$currentVal" ]; then
        val="$currentVal"
    elif [ -n "$fileVal" ]; then
        val="$(cat "$fileVal")"
    fi

    export "$var"="$val"
    unset "$fileVar"
}

file_env 'OPEN_TERMINAL_API_KEY'


# ── Helper: drop privileges to "user" ─────────────────────────────────────
#
# Detects gosu (Debian) vs su-exec (Alpine) automatically.
# Both do the same thing: exec a command as a different user.
#
drop_to_user() {
    if command -v gosu >/dev/null 2>&1; then
        exec gosu user "$@"
    elif command -v su-exec >/dev/null 2>&1; then
        exec su-exec user "$@"
    else
        # Fallback: already running as the right user
        exec "$@"
    fi
}


# ── Home directory setup ──────────────────────────────────────────────────
#
# When /home/user is bind-mounted empty, Docker doesn't populate it with
# the image contents.  We seed essential dotfiles so bash works properly.
#
fix_home() {
    local home="/home/user"

    # Fix ownership if the mount changed it (works on both GNU and BusyBox stat)
    local owner_uid
    owner_uid=$(stat -c '%u' "$home" 2>/dev/null) || owner_uid=$(stat -f '%u' "$home" 2>/dev/null) || owner_uid="1000"
    if [ "$owner_uid" != "1000" ]; then
        chown -R user:user "$home" 2>/dev/null || true
    fi

    # Seed bashrc / profile from skeleton if missing
    if [ ! -f "$home/.bashrc" ]; then
        if [ -f /etc/skel/.bashrc ]; then
            cp /etc/skel/.bashrc "$home/.bashrc" 2>/dev/null || true
        fi
    fi
    if [ ! -f "$home/.profile" ]; then
        if [ -f /etc/skel/.profile ]; then
            cp /etc/skel/.profile "$home/.profile" 2>/dev/null || true
        fi
    fi

    mkdir -p "$home/.local/bin"
    chown -R user:user "$home" 2>/dev/null || true
}


# ── Network egress filtering ──────────────────────────────────────────────
#
#   OPEN_TERMINAL_ALLOWED_DOMAINS unset    → full internet access
#   OPEN_TERMINAL_ALLOWED_DOMAINS=""       → block ALL outbound traffic
#   OPEN_TERMINAL_ALLOWED_DOMAINS="a,b"    → DNS whitelist via dnsmasq
#
# When restricted, a local dnsmasq resolves only whitelisted domains.
# iptables blocks all other outbound traffic.  CAP_NET_ADMIN is then
# permanently dropped so the rules can't be undone from inside.
#
setup_egress_firewall() {
    # Not configured — allow everything
    if [ "${OPEN_TERMINAL_ALLOWED_DOMAINS+set}" != "set" ]; then
        return 1  # signal caller: no firewall, just exec normally
    fi

    if ! command -v iptables >/dev/null 2>&1; then
        echo "WARNING: iptables not found — skipping egress firewall"
        return 1
    fi

    # Flush any prior OUTPUT rules
    iptables -F OUTPUT 2>/dev/null || true

    # Always allow loopback + established connections
    iptables -A OUTPUT -o lo -j ACCEPT
    iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

    if [ -z "$OPEN_TERMINAL_ALLOWED_DOMAINS" ]; then
        # ── Deny-all mode ──────────────────────────────────────────────
        echo "Egress: blocking ALL outbound traffic"
        iptables -A OUTPUT -j DROP
    else
        # ── Restricted mode (DNS whitelist + ipset) ────────────────────
        echo "Egress: DNS whitelist — $OPEN_TERMINAL_ALLOWED_DOMAINS"

        # Grab the current upstream nameserver before we override resolv.conf
        UPSTREAM_DNS=$(grep -m1 '^nameserver' /etc/resolv.conf | awk '{print $2}')
        UPSTREAM_DNS="${UPSTREAM_DNS:-8.8.8.8}"

        # Create ipset for dynamically resolved IPs
        ipset create allowed hash:ip -exist

        # Generate dnsmasq config:
        #   - NXDOMAIN for everything by default
        #   - Forward allowed domains to upstream DNS
        #   - Auto-add resolved IPs to the 'allowed' ipset
        mkdir -p /etc/dnsmasq.d
        {
            echo "no-resolv"
            echo "no-hosts"
            echo "listen-address=127.0.0.1"
            echo "port=53"
            echo "address=/#/"   # NXDOMAIN for everything by default

            # Process each comma-separated domain
            echo "$OPEN_TERMINAL_ALLOWED_DOMAINS" | tr ',' '\n' | while read -r domain; do
                domain=$(echo "$domain" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
                [ -z "$domain" ] && continue
                # Strip wildcard prefix — dnsmasq matches all subdomains natively
                domain="${domain#\*.}"
                echo "server=/${domain}/${UPSTREAM_DNS}"
                echo "ipset=/${domain}/allowed"
                echo "  ✓ ${domain} (+ subdomains)" >&2
            done
        } > /etc/dnsmasq.d/egress.conf

        # Start dnsmasq as a background daemon
        dnsmasq --conf-file=/etc/dnsmasq.d/egress.conf
        echo "dnsmasq started (upstream: ${UPSTREAM_DNS})"

        # Point the container at our local resolver
        echo "nameserver 127.0.0.1" > /etc/resolv.conf

        # Allow ONLY resolved IPs (via ipset) + block everything else
        iptables -A OUTPUT -p udp --dport 53 -j DROP       # block external DNS
        iptables -A OUTPUT -p tcp --dport 53 -j DROP       # block external DNS
        iptables -A OUTPUT -m set --match-set allowed dst -j ACCEPT
        iptables -A OUTPUT -j DROP                          # drop everything else
    fi

    echo "Egress firewall active — dropping CAP_NET_ADMIN permanently"
    return 0  # signal caller: firewall is active, use capsh
}


# ============================================================================
#  Main
# ============================================================================

fix_home

# Export env vars for the app user (since we're running as root, these
# won't be inherited automatically).
export HOME="/home/user"
export PATH="/home/user/.local/bin:${PATH}"

# Try to set up the egress firewall (requires running as root / CAP_NET_ADMIN).
# If the firewall was configured, drop capabilities and switch to the app user.
# If not, just switch to the app user normally.
if setup_egress_firewall; then
    # Firewall is active — drop CAP_NET_ADMIN and exec as user
    if command -v capsh >/dev/null 2>&1; then
        exec capsh --drop=cap_net_admin -- -c "
            exec $(command -v gosu 2>/dev/null || command -v su-exec 2>/dev/null || echo exec) \
                user open-terminal $*
        "
    else
        drop_to_user open-terminal "$@"
    fi
else
    drop_to_user open-terminal "$@"
fi
