import base64
import os
from typing import List, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from gradio_client import Client, handle_file
from pydantic import BaseModel

app = FastAPI(title="Wardrobe Atelier AI API")

# ---------------------------------------------------------------
# CORS — set ALLOWED_ORIGINS in Render's environment variables to
# your real Netlify URL(s), comma-separated, e.g.:
#   ALLOWED_ORIGINS=https://your-site.netlify.app,http://localhost:5173
# Falls back to "*" (any site) if not set, which is fine for testing
# but should be locked down before you share the site publicly.
# ---------------------------------------------------------------
_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
allowed_origins = ["*"] if _origins_env == "*" else [o.strip() for o in _origins_env.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Which try-on backend to use. "huggingface" is free but unreliable (shared,
# rate-limited ZeroGPU pool — see SETUP_GUIDE.md). "fashn" is a paid API
# (https://fashn.ai) that is fast and reliable; set FASHN_API_KEY to use it.
TRYON_PROVIDER = os.getenv("TRYON_PROVIDER", "huggingface")
FASHN_API_KEY = os.getenv("FASHN_API_KEY")


class OutfitItem(BaseModel):
    id: str
    category: str
    imageUrl: Optional[str] = None
    color: Optional[str] = None


class TryOnRequest(BaseModel):
    bodyType: str
    skinColor: str
    userImageUrl: str  # public URL to the profile photo (Supabase Storage)
    outfit: List[OutfitItem]  # garment items, each with a public imageUrl


@app.get("/")
@app.get("/health")
def health():
    return {"status": "ok", "provider": TRYON_PROVIDER}


# ---------------------------------------------------------------
# Hugging Face (yisol/IDM-VTON) provider
# ---------------------------------------------------------------
_hf_client = None


def get_hf_client():
    """Connect lazily, on first use, instead of at import time. Building the
    Client() at module load meant that if the Space happened to be asleep
    or overloaded when this server started, the whole API would fail to
    boot — every single request would then error, which is exactly the
    'AI is not responding' symptom."""
    global _hf_client
    if _hf_client is None:
        _hf_client = Client("yisol/IDM-VTON")
    return _hf_client


def tryon_huggingface(user_image_url: str, garment_image_url: str) -> str:
    try:
        client = get_hf_client()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=(
                "The free AI demo (Hugging Face) is unreachable right now — "
                "it may be asleep, overloaded, or out of its shared GPU quota. "
                f"Try again shortly. Details: {e}"
            ),
        )

    try:
        result = client.predict(
            dict={
                "background": handle_file(user_image_url),
                "layers": [handle_file(user_image_url)],
                "composite": None,
            },
            garm_img=handle_file(garment_image_url),
            garment_des="A top",
            is_checked=True,
            is_checked_crop=False,
            denoise_steps=30,
            seed=42,
            api_name="/tryon",
        )
    except Exception as e:
        # This is the case your popup was hitting: the shared HF GPU quota
        # ran out, or the Space's API signature changed underneath us.
        raise HTTPException(
            status_code=502,
            detail=(
                "The free AI model refused the request — most likely its shared "
                f"usage quota is exhausted right now. Details: {e}"
            ),
        )

    final_img_path = result[0]
    try:
        with open(final_img_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/webp;base64,{encoded}"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Got a result but couldn't read it: {e}")


# ---------------------------------------------------------------
# FASHN.ai provider (paid, reliable) — used if TRYON_PROVIDER=fashn
# Docs: https://docs.fashn.ai/api-reference/tryon-v1-6
# ---------------------------------------------------------------
def tryon_fashn(user_image_url: str, garment_image_url: str) -> str:
    if not FASHN_API_KEY:
        raise HTTPException(status_code=500, detail="FASHN_API_KEY is not set on the backend.")

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {FASHN_API_KEY}"}
    base_url = "https://api.fashn.ai/v1"

    run_resp = requests.post(
        f"{base_url}/run",
        headers=headers,
        json={
            "model_name": "tryon-v1.6",
            "inputs": {
                "model_image": user_image_url,
                "garment_image": garment_image_url,
                "category": "auto",
            },
        },
        timeout=30,
    )
    if not run_resp.ok:
        raise HTTPException(status_code=502, detail=f"FASHN rejected the request: {run_resp.text}")

    prediction_id = run_resp.json().get("id")
    if not prediction_id:
        raise HTTPException(status_code=502, detail="FASHN didn't return a prediction id.")

    import time

    for _ in range(30):  # poll for up to ~60s
        time.sleep(2)
        status_resp = requests.get(f"{base_url}/status/{prediction_id}", headers=headers, timeout=30)
        status_data = status_resp.json()
        if status_data.get("status") == "completed":
            outputs = status_data.get("output") or []
            if not outputs:
                raise HTTPException(status_code=502, detail="FASHN completed but returned no image.")
            return outputs[0]
        if status_data.get("status") == "failed":
            err = status_data.get("error", {})
            raise HTTPException(status_code=502, detail=f"FASHN render failed: {err.get('message', err)}")

    raise HTTPException(status_code=504, detail="FASHN took too long to respond.")


@app.post("/api/tryon/generate")
async def generate_try_on(request: TryOnRequest):
    if not request.userImageUrl:
        raise HTTPException(status_code=400, detail="A profile photo URL is required for try-on.")

    top_item = next((item for item in request.outfit if item.category == "Top"), None)
    if not top_item or not top_item.imageUrl:
        raise HTTPException(status_code=400, detail="Select a 'Top' item with an image to try on.")

    if TRYON_PROVIDER == "fashn":
        rendered = tryon_fashn(request.userImageUrl, top_item.imageUrl)
    else:
        rendered = tryon_huggingface(request.userImageUrl, top_item.imageUrl)

    return {"status": "success", "renderedImageUrl": rendered}
