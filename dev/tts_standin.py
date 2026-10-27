"""Local stand-in for the course TTS API (development only): OpenAI-style POST /v1/audio/speech served by
rumik-oss-1 (voices Ira, Aisha, Siya, Zoya; CC-BY-NC licence, fine for coursework). One clip at a time on one GPU.

  python dev/tts_standin.py --model path/to/rumik-oss-1 --port 8032   # needs torch, transformers, soundfile
Then run the web app with TTS_BASE_URL=http://<host>:8032/v1 TTS_VOICES=Ira,Aisha,Siya,Zoya
"""
import argparse
import io
import threading

import soundfile as sf
import torch
import uvicorn
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import Response
from transformers import AutoModelForCausalLM, AutoTokenizer, MimiModel

VOICES = ["Ira", "Aisha", "Siya", "Zoya"]
ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True)
ap.add_argument("--port", type=int, default=8032)
ap.add_argument("--max-new-tokens", type=int, default=3072)  # ~30 s of audio at 100 tokens/s
a = ap.parse_args()

tok = AutoTokenizer.from_pretrained(a.model, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(a.model, trust_remote_code=True, dtype=torch.bfloat16,
                                             attn_implementation="sdpa").eval().cuda()
mimi = MimiModel.from_pretrained(f"{a.model}/codec").eval().cuda()
gpu = threading.Lock()  # requests queue here; the model runs one clip at a time
app = FastAPI()


@app.post("/v1/audio/speech")
def speech(req: dict = Body(...)):
    voice, text = req.get("voice"), str(req.get("input") or "").strip()
    if voice not in VOICES or not text:
        raise HTTPException(400, f"need input text and a voice from {VOICES}")
    inputs = tok(f"<text>{voice}: {text}<audio>", return_tensors="pt").to("cuda")
    with gpu, torch.inference_mode():
        ids = model.generate_audio(**inputs, max_new_tokens=a.max_new_tokens, temperature=0.8, top_k=30, do_sample=True)
        codes = model.audio_tokens_to_codes(ids[0].tolist()[inputs.input_ids.shape[1]:]).cuda()
        wav = mimi.decode(codes).audio_values[0, 0].float().clamp(-1, 1).cpu().numpy()
    buf = io.BytesIO()
    sf.write(buf, wav, 24000, format="WAV")
    return Response(buf.getvalue(), media_type="audio/wav")


uvicorn.run(app, host="0.0.0.0", port=a.port)
