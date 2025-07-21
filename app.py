import gradio as gr
import fitz  # PyMuPDF
from pdf2image import convert_from_bytes
import pytesseract
from PIL import Image
import anthropic
import os
import textwrap

PROMPT_TEMPLATE = """Please analyze the uploaded course evaluation PDF and extract feedback in the following format:
Instructions:
Extract TWO types of feedback:
Constructive Suggestions - Rewrite harsh or mean comments into professional, actionable feedback. Focus on the underlying educational concern rather than personal attacks.
Supportive Comments - Include positive, encouraging, or particularly kind student comments as direct quotes.
What to INCLUDE:
- Specific suggestions for course improvement
- Comments about teaching methods, materials, or organization
- Constructive criticism about pacing, clarity, or structure
- Requests for additional resources or support
- Positive feedback that highlights what works well
- Comments that show genuine engagement with the learning process
What to EXCLUDE:
- Personal attacks on the instructor's character
- Complaints without constructive suggestions
- Comments that are purely emotional venting
- Inappropriate or unprofessional language
- Repetitive complaints already captured elsewhere
Output Format:
Constructive Suggestions for Improvement:
[Suggestion theme] (mentioned by X students) - [Professional rewrite of the core concern]
[Another theme] (mentioned by X students) - [Actionable feedback]
[Individual unique suggestion] (mentioned by 1 student) - [Specific concern]
Supportive Student Comments:
"[Direct quote from positive feedback]"
"[Another encouraging comment]"
"[Specific praise that could be meaningful to instructor]"
Summary:
Most Common Concerns: List the top 3-4 themes that appeared most frequently
Key Strengths Highlighted: Main positive themes from supportive comments
Unique Suggestions: Any one-off suggestions that might be worth considering
PDF Text:
"""

def extract_text_from_pdf(file_bytes):
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        return full_text.strip()
    except:
        return ""

def extract_text_via_ocr(file_bytes):
    images = convert_from_bytes(file_bytes)
    text = ""
    for img in images:
        text += pytesseract.image_to_string(img)
    return text.strip()

def summarize_feedback(pdf_file, api_key):
    if not pdf_file:
        return "❌ No PDF file was uploaded. Please upload a course evaluation PDF."
    if not api_key.strip():
        return "❌ No Claude API key was provided. Please enter a valid API key."

    try:
        file_path = pdf_file.name
        with open(file_path, "rb") as f:
            file_bytes = f.read()
    except Exception as e:
        return f"❌ Failed to read uploaded file: {str(e)}"

    # Try PyMuPDF first
    text = extract_text_from_pdf(file_bytes)

    if not text:
        text = extract_text_via_ocr(file_bytes)

    if not text:
        return "❌ No extractable text found in this PDF. It may be too low resolution or blank."

    # Send to Claude
    chunks = textwrap.wrap(text, 12000)
    client = anthropic.Anthropic(api_key=api_key)
    result = ""

    for i, chunk in enumerate(chunks):
        try:
            response = client.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=2048,
                temperature=0.3,
                messages=[{"role": "user", "content": PROMPT_TEMPLATE + chunk}]
            )
            result += f"\n\n### Claude Summary (Chunk {i+1}):\n\n" + response.content[0].text.strip()
        except Exception as e:
            result += f"\n\n❌ Claude error in chunk {i+1}: {str(e)}"
            break

    return result or "❌ Claude did not return any output."

iface = gr.Interface(
    fn=summarize_feedback,
    inputs=[
        gr.File(label="Upload Course Evaluation PDF", file_types=[".pdf"]),
        gr.Textbox(label="Claude API Key", type="password", placeholder="Paste your Claude API key here"),
    ],
    outputs=gr.Markdown(label="Summarized Feedback"),
    title="📋 Course Evaluation Summarizer with Claude",
    description="""
This app extracts feedback from course evaluation PDFs and sends it to Claude for structured analysis.
✅ Supports typed and scanned PDFs  
🔐 Claude API key is required for processing  
⚠️ If upload doesn’t work, open the app directly at: [https://rrivard-distill.hf.space](https://rrivard-distill.hf.space)
"""
)

if __name__ == "__main__":
    iface.launch()
