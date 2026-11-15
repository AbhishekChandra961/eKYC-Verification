#!/bin/sh
# Resumable download of SIDTD clips_cropped.zip (28.5 GB) into data/raw.
# The UAB server is slow (~100-150 KB/s per connection), so this can take days.
# Safe to re-run at any time: curl -C - continues from the existing partial file.
#
# Run detached (survives closing the terminal; caffeinate -i blocks idle sleep):
#   nohup caffeinate -i sh ~/Developer/ekyc-verification/scripts/download_sidtd_clips.sh \
#     > ~/Developer/ekyc-verification/data/raw/clips_cropped.download.log 2>&1 < /dev/null &
# Check progress:
#   ls -l ~/Developer/ekyc-verification/data/raw/clips_cropped.zip
#   tail ~/Developer/ekyc-verification/data/raw/clips_cropped.download.log

URL="http://datasets.cvc.uab.es/SIDTD/clips_cropped.zip"
WANT=28514444140   # Content-Length reported by the server
cd "$HOME/Developer/ekyc-verification/data/raw" || exit 1

size() { stat -f %z clips_cropped.zip 2>/dev/null || echo 0; }

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
