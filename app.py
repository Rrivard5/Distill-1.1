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
    file_bytes = pdf_file.read()
    text = extract_text_from_pdf(file_bytes)

    if not text:
        text = extract_text_via_ocr(file_bytes)

    if not text:
        return "❌ No extractable text found in this PDF."

    # Claude chunking
    chunks = textwrap.wrap(text, 12000)
    client = anthropic.Anthropic(api_key=api_key)
    result = ""

    for i, chunk in enumerate(chunks):
        response = client.messages.create(
            model="claude-3-opus-20240229",
            max_tokens=2048,
            temperature=0.3,
            messages=[
                {"role": "user", "content": PROMPT_TEMPLATE + chunk}
            ]
        )
        result += f"\n\n### Claude Summary (Chunk {i+1}):\n\n" + response.content[0].text.strip()

    return result

iface = gr.Interface(
    fn=summarize_feedback,
    inputs=[
        gr.File(label="Upload Course Evaluation PDF", file_types=[".pdf"]),
        gr.Textbox(label="Claude API Key", type="password"),
    ],
    outputs=gr.Markdown(label="Summarized Feedback"),
    title="Course Evaluation Summarizer",
    description="Upload a course eval PDF. This app extracts text (or uses OCR), sends it to Claude, and returns structured feedback."
)

if __name__ == "__main__":
    iface.launch()
