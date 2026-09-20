#!/bin/sh
# Render every proposal at 256, 48 and 24 px on light and dark, then build the
# contact sheet. Run it from the directory holding the a-*, b-*, c-* proposal
# directories; everything is written there.
set -e

LIGHT="#ffffff"
DARK="#111111"
FONT=/System/Library/Fonts/Supplemental/Arial.ttf

for dir in a-* b-* c-*; do
  [ -d "$dir" ] || continue
  for size in 256 48 24; do
    rsvg-convert --width "$size" --height "$size" --format png "$dir/icon.svg" -o "$dir/icon-$size.png"
    magick "$dir/icon-$size.png" -background "$LIGHT" -flatten "$dir/light-$size.png"
    magick "$dir/icon-$size.png" -background "$DARK"  -flatten "$dir/dark-$size.png"
  done
done

# Contact sheet: one column per proposal, one band per background, sizes side by side.
build_band () {  # $1 = light|dark, $2 = background, $3 = label colour
  for dir in a-* b-* c-*; do
    magick \
      \( "$dir/$1-256.png" \) \
      \( "$dir/$1-48.png" -background "$2" -gravity center -extent 96x256 \) \
      \( "$dir/$1-24.png" -background "$2" -gravity center -extent 72x256 \) \
      +append -background "$2" -bordercolor "$2" -border 24 \
      -font "$FONT" -fill "$3" -pointsize 20 -gravity north -annotate +0+4 "$dir" \
      -gravity southwest -annotate +30+6 "256" \
      -gravity south -annotate +64+6 "48" \
      -gravity southeast -annotate +38+6 "24" \
      "sheet-$1-$dir.png"
  done
  magick sheet-"$1"-a-* sheet-"$1"-b-* sheet-"$1"-c-* -background "$2" +append "band-$1.png"
  rm -f sheet-"$1"-*.png
}

build_band light "$LIGHT" "#111111"
build_band dark "$DARK" "#ffffff"

magick band-light.png band-dark.png -background "#808080" -append kontaktark.png
rm -f band-light.png band-dark.png
echo "wrote kontaktark.png"
