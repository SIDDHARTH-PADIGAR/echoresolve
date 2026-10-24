set -e
apt-get update -qq
apt-get install -y -qq curl >/dev/null
cd /models
for f in \
  LFM2.5-Audio-1.5B-Q4_0.gguf \
  mmproj-LFM2.5-Audio-1.5B-Q4_0.gguf \
  tokenizer-LFM2.5-Audio-1.5B-Q4_0.gguf \
  vocoder-LFM2.5-Audio-1.5B-Q4_0.gguf
do
  if [ ! -s "$f" ]; then
    echo "Downloading $f"
    curl -fL --retry 3 -o "$f" "https://huggingface.co/LiquidAI/LFM2.5-Audio-1.5B-GGUF/resolve/main/$f?download=true"
  else
    echo "Already present: $f"
  fi
done
ls -lh
