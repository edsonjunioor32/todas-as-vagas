#!/usr/bin/env bash
set -euo pipefail

# Rendered public portals run on the self-hosted ARM64 runner. Selenium Manager
# can download a driver for the wrong architecture, so provision and export a
# native browser/driver pair before any collector imports Selenium.
if [ "${SKIP_CHROMIUM_PROVISION:-0}" = "1" ]; then
  echo "Provisionamento do Chromium ignorado por SKIP_CHROMIUM_PROVISION=1."
  exit 0
fi

case "$(uname -m)" in
  aarch64|arm64)
    ;;
  *)
    echo "ERRO: este passo exige um runner ARM64; arquitetura detectada: $(uname -m)" >&2
    exit 1
    ;;
esac

resolve_executable() {
  local candidate resolved
  for candidate in "$@"; do
    [ -n "$candidate" ] || continue
    if [[ "$candidate" == */* ]]; then
      resolved="$candidate"
    else
      resolved="$(command -v "$candidate" 2>/dev/null || true)"
    fi
    if [ -n "$resolved" ] && [ -f "$resolved" ] && [ -x "$resolved" ]; then
      printf '%s\n' "$resolved"
      return 0
    fi
  done
  return 1
}

browser_binary=""
driver_binary=""

find_pair() {
  browser_binary="$(resolve_executable \
    "${CHROME_BINARY:-}" \
    "${CHROMIUM_BINARY:-}" \
    chromium chromium-browser google-chrome google-chrome-stable || true)"
  driver_binary="$(resolve_executable \
    "${CHROMEDRIVER_PATH:-}" \
    chromedriver || true)"
  [ -n "$browser_binary" ] && [ -n "$driver_binary" ]
}

validate_pair() {
  [ -n "${browser_binary:-}" ] && [ -n "${driver_binary:-}" ] || return 1
  echo "Navegador: $browser_binary"
  echo "Driver: $driver_binary"
  "$browser_binary" --version
  "$driver_binary" --version

  # Status 127 here is the exact failure previously observed in collection
  # (the downloaded ARM64 chromedriver could not execute on the VPS).
  if command -v ldd >/dev/null 2>&1 && file "$driver_binary" 2>/dev/null | grep -q "ELF"; then
    if ldd "$driver_binary" 2>&1 | grep -q "not found"; then
      echo "ERRO: o ChromeDriver possui bibliotecas nativas ausentes." >&2
      ldd "$driver_binary" >&2 || true
      return 1
    fi
  fi
}

if find_pair && validate_pair; then
  echo "Par Chromium/ChromeDriver nativo já disponível."
else
  echo "Par nativo ausente ou inválido; instalando pacotes do sistema."
  export DEBIAN_FRONTEND=noninteractive

  browser_package=""
  for package in chromium chromium-browser; do
    if apt-cache show "$package" >/dev/null 2>&1; then
      browser_package="$package"
      break
    fi
  done

  driver_package=""
  for package in chromium-driver chromium-chromedriver; do
    if apt-cache show "$package" >/dev/null 2>&1; then
      driver_package="$package"
      break
    fi
  done

  if [ -z "$browser_package" ] || [ -z "$driver_package" ]; then
    echo "ERRO: não encontrei pacotes ARM64 compatíveis de Chromium/ChromeDriver nos repositórios APT." >&2
    echo "Pacotes detectados: browser=${browser_package:-nenhum}, driver=${driver_package:-nenhum}" >&2
    exit 1
  fi

  sudo -n apt-get update
  sudo -n apt-get install -y --no-install-recommends "$browser_package" "$driver_package"

  browser_binary=""
  driver_binary=""
  find_pair || true
  if ! validate_pair; then
    echo "ERRO: Chromium/ChromeDriver foram instalados, mas não executam neste runner." >&2
    exit 1
  fi
fi

if [ -n "${GITHUB_ENV:-}" ]; then
  {
    echo "CHROME_BINARY=$browser_binary"
    echo "CHROMEDRIVER_PATH=$driver_binary"
  } >> "$GITHUB_ENV"
fi

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "### Navegador nativo ARM64"
    echo
    echo "- Chromium: `$browser_binary`"
    echo "- ChromeDriver: `$driver_binary`"
  } >> "$GITHUB_STEP_SUMMARY"
fi

echo "Chromium/ChromeDriver nativos validados e exportados para o Selenium."
