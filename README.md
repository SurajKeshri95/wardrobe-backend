# Wardrobe Atelier — Backend

FastAPI backend for the AI virtual try-on feature of **Wardrobe Atelier**, a personal wardrobe organizer. The frontend lives in [wardrobe-frontend](https://github.com/SurajKeshri95/wardrobe-frontend).

> **Status: try-on is currently on hold.** The frontend shows a "coming soon" message instead of calling this API. See [Known issues](#known-issues) for why.

## What it does

Takes a photo of the user and a photo of a garment, sends them to an AI try-on model, and returns an image of the user wearing the garment.

Images are passed as **public URLs** (hosted in Supabase Storage), not as base64 data, which keeps requests small and fast.

## Tech stack

- Python + [FastAPI](https://fastapi.tiangolo.com/)
- Uvicorn (server)
- `gradio_client` (Hugging Face provider)
- `requests` (FASHN provider)
- Hosted on [Render](https://render.com)

## API

### `GET /` and `GET /health`
Health check. Returns the active provider.
```json
{ "status": "ok", "provider": "huggingface" }
```

### `POST /api/tryon/generate`
Request body:
```json
{
  "bodyType": "rectangle",
  "skinColor": "#D9A374",
  "userImageUrl": "https://.../profile/photo.png",
  "outfit": [
    { "id": "abc", "category": "Top", "imageUrl": "https://.../items/shirt.png" }
  ]
}
```
Success response:
```json
{ "status": "success", "renderedImageUrl": "data:image/webp;base64,..." }
```
Errors return a JSON `detail` message with a status of `400` (missing photo or Top item), `502`/`503` (AI provider failed or unreachable), or `504` (timeout).

**Current limitation:** only the `Top` item in an outfit is rendered. Other categories are ignored.

## Try-on providers

Pick one with the `TRYON_PROVIDER` environment variable.

| Provider | Value | Cost | Notes |
|---|---|---|---|
| Hugging Face (`yisol/IDM-VTON`) | `huggingface` (default) | Free | Shared GPU quota, often unreliable |
| FASHN | `fashn` | Paid, per render | Fast and reliable, needs an API key |

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `ALLOWED_ORIGINS` | Recommended | Comma-separated frontend URLs allowed by CORS, e.g. `https://your-site.netlify.app,http://localhost:5173`. Defaults to `*` (any site). |
| `TRYON_PROVIDER` | No | `huggingface` (default) or `fashn` |
| `FASHN_API_KEY` | Only for `fashn` | API key from [fashn.ai](https://fashn.ai) |

## Run locally

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```
The API runs at `http://localhost:8000`, with interactive docs at `/docs`.

## Deploy on Render

1. Create a **Web Service** connected to this repo.
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add the environment variables above.

## Known issues

- **Out-of-memory crashes on Render's free tier.** The free plan has a 512 MB limit, and loading `gradio_client` for the Hugging Face provider can exceed it, which restarts the service mid-request.
- **Hugging Face quota.** `yisol/IDM-VTON` runs on a shared ZeroGPU pool. Anonymous API calls are heavily throttled, so requests can fail even when the server is healthy.
- **Single garment.** Only the Top category is sent to the model.

**Planned fix:** switch to the `fashn` provider. It is a lightweight HTTP call, so it avoids the memory problem, and it responds reliably.

## Project structure

```
main.py             FastAPI app, CORS, both try-on providers
requirements.txt    Python dependencies
```
