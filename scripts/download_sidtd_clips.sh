#!/bin/sh
# Resumable download of SIDTD clips_cropped.zip (28.5 GB) into data/raw.
# The UAB server is slow (~100-150 KB/s per connection), so this can take days.
# Safe to re-run at any time: curl -C - continues from the existing partial file.
#
# Run detached from the project root (survives closing the terminal; on macOS caffeinate -i blocks idle sleep):
#   mkdir -p data/raw
#   nohup caffeinate -i sh scripts/download_sidtd_clips.sh > data/raw/clips_cropped.download.log 2>&1 < /dev/null &
# Check progress:
#   ls -l data/raw/clips_cropped.zip
#   tail data/raw/clips_cropped.download.log
# Then unpack (read-only source data from here on):  unzip -q data/raw/clips_cropped.zip -d data/interim/

URL="http://datasets.cvc.uab.es/SIDTD/clips_cropped.zip"
WANT=28514444140   # Content-Length reported by the server
cd "$(dirname "$0")/../data/raw" || exit 1   # the project's data/raw, wherever the project was cloned

size() { [ -f clips_cropped.zip ] && wc -c < clips_cropped.zip | tr -d ' ' || echo 0; }  # portable (macOS + Linux)

attempt=0
while [ "$(size)" -lt "$WANT" ] && [ "$attempt" -lt 500 ]; do
  attempt=$((attempt + 1))
  echo "$(date '+%F %T') attempt $attempt starting at $(size) bytes"
  # Abort a stalled connection (<1 KB/s for 5 min) so the loop can reconnect and resume.
  curl -L -C - --silent --show-error --speed-limit 1000 --speed-time 300 \
       -o clips_cropped.zip "$URL"
  echo "$(date '+%F %T') curl exit=$? size=$(size)"
  [ "$(size)" -lt "$WANT" ] && sleep 30
done

if [ "$(size)" -eq "$WANT" ]; then
  echo "$(date '+%F %T') DONE: clips_cropped.zip complete ($WANT bytes)"
else
  echo "$(date '+%F %T') STOPPED: size=$(size), expected $WANT"
fi
