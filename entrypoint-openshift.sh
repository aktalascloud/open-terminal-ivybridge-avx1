#!/bin/sh
set -e

file_env() {
    var="$1"
    file_var="${var}_FILE"
    default="${2:-}"

    eval current_value="\${$var:-}"
    eval file_value="\${$file_var:-}"
    eval var_is_set="\${$var+set}"
    eval file_is_set="\${$file_var+set}"

    if [ "$var_is_set" = "set" ] && [ "$file_is_set" = "set" ]; then
        printf >&2 'error: both %s and %s are set, but they are mutually exclusive\n' "$var" "$file_var"
        exit 1
    fi

    value="$default"
    if [ -n "$current_value" ]; then
        value="$current_value"
    elif [ -n "$file_value" ]; then
        value="$(cat "$file_value")"
    fi

    export "$var=$value"
    unset "$file_var"
}

warn_unsupported() {
    var="$1"
    eval value="\${$var:-}"
    if [ -n "$value" ]; then
        printf >&2 'warning: %s is not supported by the OpenShift image and will be ignored\n' "$var"
        unset "$var"
    fi
}

file_env OPEN_TERMINAL_API_KEY

if [ "${OPEN_TERMINAL_MULTI_USER:-}" = "true" ] || [ "${OPEN_TERMINAL_MULTI_USER:-}" = "1" ]; then
    printf >&2 'error: OPEN_TERMINAL_MULTI_USER is not supported by the OpenShift image\n'
    exit 1
fi

warn_unsupported OPEN_TERMINAL_ALLOWED_DOMAINS
warn_unsupported OPEN_TERMINAL_PACKAGES
warn_unsupported OPEN_TERMINAL_PIP_PACKAGES
warn_unsupported OPEN_TERMINAL_NPM_PACKAGES

export HOME="${HOME:-/home/user}"
export SHELL="${SHELL:-/bin/bash}"
export USER="${USER:-user}"
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
export XDG_STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
export PATH="$HOME/.local/bin:$PATH"

mkdir -p "$HOME" "$HOME/.local/bin" "$XDG_CONFIG_HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME" 2>/dev/null || true

exec open-terminal "$@"
