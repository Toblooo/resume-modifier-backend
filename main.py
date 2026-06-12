from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

import shutil
import uuid
import os

from resume_script import tailor_resume

app = FastAPI()

os.makedirs("uploads", exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

@app.get("/")
def read_root():
    return RedirectResponse(url="/docs")


@app.post("/tailor")
async def tailor(
    resume: UploadFile = File(...),
    job_description: str = Form(...)
):
    session = str(uuid.uuid4())

    input_docx = f"uploads/{session}.docx"
    output_docx = f"uploads/{session}_tailored.docx"

    try:
        # Save uploaded resume
        with open(input_docx, "wb") as f:
            shutil.copyfileobj(resume.file, f)

        # Run resume processing (NOW ONLY DOCX OUTPUT)
        tailor_resume(
            input_docx,
            job_description,
            output_docx
        )

        # Ensure file exists
        if not os.path.exists(output_docx):
            raise HTTPException(
                status_code=500,
                detail="Resume script failed to generate DOCX file."
            )

        # ✅ RETURN DOCX INSTEAD OF PDF
        return FileResponse(
            output_docx,
            filename="tailored_resume.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Backend Error: {str(e)}"
        )