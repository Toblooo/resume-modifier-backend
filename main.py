from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.background import BackgroundTasks

import shutil
import uuid
import os

from resume_script import tailor_resume

app = FastAPI()

# =========================
# ENVIRONMENT SETUP (RENDER SAFE)
# =========================
os.makedirs("uploads", exist_ok=True)

# Fetch your local Ollama tunnel URL from Render's Environment Variables
LOCAL_AI_URL = os.environ.get("LOCAL_AI_URL")
CACHE_FILE = "resume_cache.json"

# =========================
# CORS CONFIG (Vercel + LOCAL + PRODUCTION)
# =========================
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://resume-modifier-frontend.vercel.app"
    "https://resume-modifier-frontend-o159k8wai-toblooos-projects.vercel.app"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# Expanded helper function to clear files and cache after response is sent
def cleanup_files(*filepaths: str):
    # 1. Clean up requested filepaths (input and output .docx files)
    for path in filepaths:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
                
    # 2. Force clear the LLM resume cache file if it exists
    if os.path.exists(CACHE_FILE):
        try:
            os.remove(CACHE_FILE)
            print("Successfully cleared resume_cache.json")
        except Exception as e:
            print(f"Failed to clear cache file: {e}")

# =========================
# HEALTH CHECK (useful for Render)
# =========================
@app.get("/health")
def health():
    return {"status": "ok"}

# =========================
# ROOT (redirect to docs)
# =========================
@app.get("/")
def read_root():
    return RedirectResponse(url="/docs")

# =========================
# MAIN ENDPOINT
# =========================
@app.post("/tailor")
async def tailor(
    background_tasks: BackgroundTasks,
    resume: UploadFile = File(...),
    job_description: str = Form(...)
):
    # Guard check: Ensure you provided the tunnel link to Render
    if not LOCAL_AI_URL:
        raise HTTPException(
            status_code=500,
            detail="Server Configuration Error: 'LOCAL_AI_URL' environment variable is missing on Render."
        )

    session_id = str(uuid.uuid4())
    input_docx = f"uploads/{session_id}.docx"
    output_docx = f"uploads/{session_id}_tailored.docx"

    try:
        # Save uploaded file
        with open(input_docx, "wb") as f:
            shutil.copyfileobj(resume.file, f)

        # Run AI tailoring logic passing the tunnel URL
        await tailor_resume(
            input_docx,
            job_description,
            output_docx,
            LOCAL_AI_URL
        )

        # Validate output
        if not os.path.exists(output_docx):
            raise HTTPException(
                status_code=500,
                detail="Resume generation failed (no output file was created by the AI script)."
            )

        # Trigger background task to clear everything right after the file streams down to Vercel
        background_tasks.add_task(cleanup_files, input_docx, output_docx)

        # Return file
        return FileResponse(
            path=output_docx,
            filename="tailored_resume.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    except Exception as e:
        # Critical cleanup fallback if code breaks midway
        cleanup_files(input_docx, output_docx)
        raise HTTPException(
            status_code=500,
            detail=f"Backend error: {str(e)}"
        )

# =========================
# RENDER ENTRYPOINT FIX
# =========================
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)