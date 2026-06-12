from docx import Document
import httpx  # Changed from requests for async compatibility
import shutil
import os
import re
import asyncio
import json
import hashlib

# ================== CONFIGURATION ==================
MODEL = "llama3.1:8b"
DELAY_BETWEEN_CALLS = 0.1  # Reduced since async can yield naturally
CACHE_FILE = "resume_cache.json"
# ===================================================

# Modified to accept dynamic url via async httpx client
async def ollama_chat(client, ollama_url, prompt, model=MODEL, temperature=0.1, num_predict=300):
    base_url = ollama_url.rstrip('/')
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "options": {
            "temperature": temperature,
            "num_predict": num_predict
        },
        "stream": False
    }
    
    response = await client.post(f"{base_url}/api/chat", json=payload, timeout=120)
    response.raise_for_status()
    return response.json()


async def check_and_pull_model(client, ollama_url, model_name):
    print(f"Checking remote Ollama model: {model_name}")
    try:
        await ollama_chat(client, ollama_url, "hi", model=model_name, num_predict=5)
        print("Remote Ollama ready")
    except Exception as e:
        print(f"Ollama connection warning: {e}")


def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_cache(cache):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Failed to write cache file: {e}")


def get_cache_key(text, keywords):
    return hashlib.md5((text + "|" + keywords).encode()).hexdigest()


async def extract_ats_keywords(client, ollama_url, job_description):
    prompt = f"""
Extract the 20 most important ATS keywords, hard skills, and phrases.
Return ONLY comma separated values.

JOB DESCRIPTION:
{job_description}
"""
    response = await ollama_chat(client, ollama_url, prompt, model=MODEL, temperature=0.1, num_predict=300)
    return response["message"]["content"].strip()


def is_likely_bullet(text):
    if len(text) < 25:
        return False

    bullets = ["•", "·", "-", "▪", "■", "◆", "*"]
    if any(text.startswith(x) for x in bullets):
        return True

    verbs = {
        "led", "managed", "developed", "created", "implemented", 
        "built", "designed", "optimized", "analyzed", "engineered", 
        "automated", "improved"
    }
    words = text.split()
    if words and words[0].lower() in verbs:
        return True
    return False


def process_paragraph_for_extraction(text, section, role, bullets):
    if not text:
        return

    if "skills" in section.lower() and "," in text and not is_likely_bullet(text):
        bullets.append({
            "original": text,
            "clean": text,
            "section": section,
            "role": "Technical Skills",
            "is_skills": True
        })
        return

    if is_likely_bullet(text):
        clean = re.sub(r'^[•·\-▪■◆*–—\s]+', '', text).strip()
        bullets.append({
            "original": text,
            "clean": clean,
            "section": section,
            "role": role,
            "is_skills": False
        })


def extract_bullets_with_context(doc):
    bullets = []
    section = ""
    role = ""

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        if len(text) < 70 and any(x in text.lower() for x in ["experience", "projects", "skills", "education"]):
            section = text
            continue

        process_paragraph_for_extraction(text, section, role, bullets)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    process_paragraph_for_extraction(p.text.strip(), section, role, bullets)

    return bullets


async def rewrite_single_bullet(client, ollama_url, bullet, job_keywords, cache):
    cache_key = get_cache_key(bullet["clean"], job_keywords)
    if cache_key in cache:
        return cache[cache_key]

    if bullet.get("is_skills", False):
        prompt = f"""
You are an expert resume writer and ATS optimization specialist.

ATS KEYWORDS: {job_keywords}
ORIGINAL SKILLS: {bullet['clean']}

TASK:
Rewrite this technical skills list to optimize for the ATS keywords.

RULES:
- Reorder the list so that skills matching the ATS keywords appear FIRST.
- Rename existing skills to perfectly match the ATS keyword phrasing if they are synonymous.
- Maintain the original structural formatting.

OUTPUT FORMATTING:
- Return ONLY the raw rewritten skills text.
- NEVER explain your changes, add commentary, or include introductory/closing thoughts.
- CRITICAL: Do NOT write things like "I integrated relevant ATS keywords...".
"""
    else:
        prompt = f"""
You are an expert resume writer and ATS optimization specialist.

SECTION CONTEXT: {bullet['section']}
ROLE CONTEXT: {bullet['role']}
ATS KEYWORDS: {job_keywords}

ORIGINAL BULLET:
{bullet['clean']}

TASK:
Rewrite the bullet to naturally integrate relevant ATS keywords while preserving the exact core accomplishment.

RULES:
- Maintain the exact same metrics, business impact, and original core meaning.
- Start with a strong, past-tense action verb (unless it's a current role).
- Ensure perfect grammar and avoid AI-sounding buzzwords.

OUTPUT FORMATTING:
- Return ONLY the raw rewritten bullet point text.
- Do NOT include bullet point characters (like -, •, or *) at the beginning.
- NEVER explain your changes, add commentary, or include introductory/closing thoughts.
- CRITICAL: Do NOT write things like "I integrated relevant ATS keywords...".
"""

    try:
        response = await ollama_chat(
            client, ollama_url, prompt, model=MODEL, temperature=0.1, num_predict=150
        )

        new_bullet = response["message"]["content"].strip()

        # 1. Broadly sweep and eliminate full conversational sentences explaining the integration
        new_bullet = re.sub(r'(I integrated relevant ATS keywords|I have rewritten this|Here is the rewritten).*?(\n|$)', '', new_bullet, flags=re.IGNORECASE)
        
        # 2. Keep the original cleanup sweeps for lines starting with conversational markers
        new_bullet = re.sub(r'^(Here is|Sure|Note:|I have|I\'ve).*?(\n|$)', '', new_bullet, flags=re.IGNORECASE | re.MULTILINE)
        
        # Remove empty buffer lines
        new_bullet = "\n".join([line for line in new_bullet.split("\n") if line.strip() != ""])
        
        # Strip trailing/leading structural bullet elements
        new_bullet = re.sub(r'^[-•·▪■◆*–—\s]+', '', new_bullet).strip()

        if new_bullet:
            cache[cache_key] = new_bullet
            return new_bullet
        return bullet["clean"]

    except Exception as e:
        print(f"Rewrite error: {e}")
        return bullet["clean"]


def replace_text(paragraph, old, new):
    if paragraph.text.strip() == old:
        # Style preservation: Clear existing run text text safely except the first run
        # This keeps paragraph styles intact.
        if paragraph.runs:
            paragraph.runs[0].text = new
            for run in paragraph.runs[1:]:
                run.text = ""
            return True
    return False


# Main entry point rewritten to support Async invocation from FastAPI
async def tailor_resume(resume_path, job_description, output_docx, ollama_url):
    print("Starting async resume tailoring orchestration...")
    cache = load_cache()
    
    # Instantiate the asynchronous HTTP pipeline
    async with httpx.AsyncClient(timeout=150.0) as client:
        await check_and_pull_model(client, ollama_url, MODEL)
        
        doc = Document(resume_path)
        keywords = await extract_ats_keywords(client, ollama_url, job_description)
        bullets = extract_bullets_with_context(doc)

        changes = {}
        for bullet in bullets:
            rewritten = await rewrite_single_bullet(client, ollama_url, bullet, keywords, cache)
            if rewritten:
                changes[bullet["original"]] = rewritten
            await asyncio.sleep(DELAY_BETWEEN_CALLS)

        save_cache(cache)

    # Document writing phase
    shutil.copy2(resume_path, output_docx)
    new_doc = Document(output_docx)
    replaced = 0

    for para in new_doc.paragraphs:
        if para.text.strip() in changes:
            if replace_text(para, para.text.strip(), changes[para.text.strip()]):
                replaced += 1

    for table in new_doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    if para.text.strip() in changes:
                        if replace_text(para, para.text.strip(), changes[para.text.strip()]):
                            replaced += 1

    new_doc.save(output_docx)
    print(f"Finished processing document structure. Replaced {replaced} structural objects.")
    return output_docx