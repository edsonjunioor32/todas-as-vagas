#!/usr/bin/env bash
set -euo pipefail

# Rendered public portals run on the self-hosted ARM64 runner. The Ubuntu
# Chromium Snap driver exits with status 1 in the headless systemd runner, so
# use the matching official Chrome for Testing ARM64 browser and driver.
if [ "${SKIP_CHROMIUM_PROVISION:-0}" = "1" ]; then
  echo "Provisionamento do navegador ignorado por SKIP_CHROMIUM_PROVISION=1."
  exit 0
fi

if [ "$(uname -m)" != "aarch64" ] && [ "$(uname -m)" != "arm64" ]; then
  echo "ERRO: este passo exige runner ARM64; arquitetura detectada: $(uname -m)" >&2
  exit 1
fi

for command_name in curl python3 timeout; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "ERRO: comando necessário ausente: $command_name" >&2
    exit 1
  fi
done

cache_root="$HOME/.cache/todas-as-vagas/chrome-for-testing"
install_root="$cache_root/stable"
mkdir -p "$cache_root"
temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/todas-vagas-cft.XXXXXX")"
next_install=""
backup_install=""
cleanup() {
  rm -rf -- "$temp_dir"
  if [ -n "$next_install" ] && [ -d "$next_install" ]; then
    rm -rf -- "$next_install"
  fi
  if [ -n "$backup_install" ] && [ -d "$backup_install" ]; then
    if [ ! -e "$install_root" ]; then
      mv "$backup_install" "$install_root" || true
    else
      rm -rf -- "$backup_install"
    fi
  fi
}
trap cleanup EXIT

manifest_file="$temp_dir/last-known-good-versions.json"
manifest_url="https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"
curl --fail --location --silent --show-error --retry 3 --connect-timeout 20 --max-time 90 \
  "$manifest_url" --output "$manifest_file"

mapfile -t release_data < <(python3 - "$manifest_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    stable = json.load(source)["channels"]["Stable"]

def asset(name):
    for item in stable["downloads"][name]:
        if item["platform"] == "linux-arm64":
            return item["url"]
    raise SystemExit(f"Stable Chrome for Testing has no linux-arm64 {name} asset")

print(stable["version"])
print(asset("chrome"))
print(asset("chromedriver"))
PY
)

if [ "${#release_data[@]}" -ne 3 ]; then
  echo "ERRO: metadados incompletos do Chrome for Testing ARM64." >&2
  exit 1
fi

version="${release_data[0]}"
chrome_url="${release_data[1]}"
driver_url="${release_data[2]}"
chrome_binary="$install_root/chrome-linux-arm64/chrome"
driver_binary="$install_root/chromedriver-linux-arm64/chromedriver"

if [ ! -x "$chrome_binary" ] || [ ! -x "$driver_binary" ] || \
   [ ! -f "$install_root/version" ] || [ "$(<"$install_root/version")" != "$version" ]; then
  stage="$temp_dir/stage"
  next_install="$(mktemp -d "$cache_root/.stable-next.XXXXXX")"
  backup_install="$(mktemp -d "$cache_root/.stable-backup.XXXXXX")"
  rmdir "$backup_install"
  mkdir -p "$stage"

  curl --fail --location --silent --show-error --retry 3 --connect-timeout 20 --max-time 300 \
    "$chrome_url" --output "$temp_dir/chrome.zip"
  curl --fail --location --silent --show-error --retry 3 --connect-timeout 20 --max-time 180 \
    "$driver_url" --output "$temp_dir/chromedriver.zip"

  python3 - "$temp_dir/chrome.zip" "$temp_dir/chromedriver.zip" "$stage" <<'PY'
import sys
import zipfile

for archive, destination in zip(sys.argv[1:3], [sys.argv[3], sys.argv[3]]):
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(destination)
PY

  test -x "$stage/chrome-linux-arm64/chrome"
  test -x "$stage/chromedriver-linux-arm64/chromedriver"
  mv "$stage/chrome-linux-arm64" "$next_install/"
  mv "$stage/chromedriver-linux-arm64" "$next_install/"
  printf '%s\n' "$version" > "$next_install/version"

  if [ -e "$install_root" ]; then
    mv "$install_root" "$backup_install"
  fi
  if ! mv "$next_install" "$install_root"; then
    if [ -e "$backup_install" ]; then
      mv "$backup_install" "$install_root"
    fi
    echo "ERRO: não foi possível ativar o Chrome for Testing $version." >&2
    exit 1
  fi
  if [ -e "$backup_install" ]; then
    rm -rf -- "$backup_install"
  fi
fi

if command -v ldd >/dev/null 2>&1; then
  for binary in "$chrome_binary" "$driver_binary"; do
    if ldd "$binary" 2>&1 | grep -q "not found"; then
      echo "ERRO: faltam bibliotecas nativas para $binary:" >&2
      ldd "$binary" >&2 || true
      exit 1
    fi
  done
fi

browser_version="$(timeout 30s "$chrome_binary" --version)"
driver_version="$(timeout 30s "$driver_binary" --version)"
echo "Navegador: $chrome_binary ($browser_version)"
echo "Driver: $driver_binary ($driver_version)"
if [[ "$browser_version" != *"$version"* ]] || [[ "$driver_version" != *"$version"* ]]; then
  echo "ERRO: versões divergentes no par Chrome/ChromeDriver ($version)." >&2
  exit 1
fi

# Exercise the browser binary now; the Selenium smoke check runs after Python
# dependencies are installed and before any portal is collected.
timeout 30s "$chrome_binary" --headless=new --no-sandbox --disable-dev-shm-usage \
  --disable-gpu --disable-extensions --disable-background-networking \
  --disable-notifications --dump-dom 'data:text/html,<title>browser-smoke-ok</title>' \
  > "$temp_dir/browser-smoke.html"
if ! grep -q "browser-smoke-ok" "$temp_dir/browser-smoke.html"; then
  echo "ERRO: Chromium não concluiu o teste headless." >&2
  exit 1
fi

if [ -n "${GITHUB_ENV:-}" ]; then
  {
    echo "CHROME_BINARY=$chrome_binary"
    echo "CHROMEDRIVER_PATH=$driver_binary"
  } >> "$GITHUB_ENV"
fi

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "### Chrome for Testing ARM64"
    echo
    echo "- Chromium: $browser_version"
    echo "- ChromeDriver: $driver_version"
    echo "- Cache persistente: $install_root"
  } >> "$GITHUB_STEP_SUMMARY"
fi

echo "Chrome for Testing/ChromeDriver ARM64 instalados e verificados."
