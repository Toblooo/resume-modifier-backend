from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

import shutil
import uuid
import os

from resume_script import tailor_resume

app = FastAPI()

# FIX 1: Automatically create the uploads directory if it doesn't exist
os.makedirs("uploads", exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], # Explicitly name them
    allow_credentials=True, # Now this is allowed safely
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

@app.post("/tailor")
async def tailor(
    resume: UploadFile = File(...),
    job_description: str = Form(...)
):
    session = str(uuid.uuid4())

    input_docx = f"uploads/{session}.docx"
    output_docx = f"uploads/{session}_tailored.docx"
    output_pdf = f"uploads/{session}_tailored.pdf"

    # FIX 4: Wrap in try/except so Python errors are caught and returned safely
    try:
        # Save the uploaded file
        with open(input_docx, "wb") as f:
            shutil.copyfileobj(resume.file, f)

        # Run your processing script
        tailor_resume(
            input_docx,
            job_description,
            output_docx,
            output_pdf
        )

        # Verify the script actually generated the file before trying to send it
        if not os.path.exists(output_pdf):
            raise HTTPException(status_code=500, detail="The resume script failed to generate the PDF file.")

        return FileResponse(
            output_pdf,
            filename="tailored_resume.pdf",
            media_type="application/pdf"
        )

    except Exception as e:
        # This forces FastAPI to send a clean JSON error, preserving your CORS headers
        raise HTTPException(status_code=500, detail=f"Backend Error: {str(e)}")