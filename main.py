from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import base64
import os
import uuid
from gradio_client import Client, handle_file

app = FastAPI(title="Wardrobe Atelier AI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Changed from localhost to *
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class OutfitItem(BaseModel):
    id: str
    category: str
    imageUrl: Optional[str] = None
    color: Optional[str] = None

class TryOnRequest(BaseModel):
    bodyType: str
    skinColor: str
    userImage: Optional[str] = None
    outfit: List[OutfitItem]

def save_temp_image(base64_string: str, prefix: str) -> str:
    if not base64_string or not base64_string.startswith("data:image"):
        return None
    header, encoded = base64_string.split(",", 1)
    file_ext = header.split(";")[0].split("/")[1]
    os.makedirs("temp", exist_ok=True)
    filepath = f"temp/{prefix}_{uuid.uuid4().hex[:8]}.{file_ext}"
    with open(filepath, "wb") as f:
        f.write(base64.b64decode(encoded))
    return filepath

# Connect to the Hugging Face IDM-VTON Space
hf_client = Client("yisol/IDM-VTON")

@app.post("/api/tryon/generate")
async def generate_try_on(request: TryOnRequest):
    try:
        # 1. Require a human image for the AI to map onto
        human_img_path = save_temp_image(request.userImage, "human")
        if not human_img_path:
            raise HTTPException(status_code=400, detail="A user photo is required in your Profile for the AI try-on.")
        
        # 2. Extract the Top garment
        top_item = next((item for item in request.outfit if item.category == "Top"), None)
        if not top_item or not top_item.imageUrl:
            raise HTTPException(status_code=400, detail="Please upload a photo of a 'Top' to your wardrobe and select it.")
        
        garment_img_path = save_temp_image(top_item.imageUrl, "garment")
        
        print("Sending images to Hugging Face IDM-VTON... (This may take 15-30 seconds)")
        
        # 3. Request the image from the AI model
        result = hf_client.predict(
            dict={"background": handle_file(human_img_path), "layers": [handle_file(human_img_path)], "composite": None},
            garm_img=handle_file(garment_img_path),
            garment_des="A top",
            is_checked=True,
            is_checked_crop=False,
            denoise_steps=30,
            seed=42,
            api_name="/tryon"
        )
        
        final_img_path = result[0]
        
        # 4. Send it back to React
        with open(final_img_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            output_data_uri = f"data:image/webp;base64,{encoded_string}"
            
        return {
            "status": "success",
            "renderedImageUrl": output_data_uri
        }

    except Exception as e:
        print("AI Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))