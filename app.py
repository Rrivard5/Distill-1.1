import gradio as gr
import fitz  # PyMuPDF
from pdf2image import convert_from_bytes
import pytesseract
from PIL import Image
import anthropic
import os
import textwrap
import tempfile

# Custom CSS for professional styling
custom_css = """
#title {
    text-align: center;
    background: linear-gradient(45deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 2rem;
    border-radius: 10px;
    margin-bottom: 2rem;
}
#description {
    text-align: center;
    font-size: 1.1em;
    color: #666;
    margin-bottom: 2rem;
    padding: 1rem;
    background-color: #f8f9fa;
    border-radius: 8px;
    border-left: 4px solid #667eea;
}
.gradio-container {
    max-width: 900px !important;
    margin: auto !important;
}
#upload_section {
    background-color: #ffffff;
    border-radius: 10px;
    padding: 1.5rem;
    margin: 1rem 0;
    box-shadow: 0 2px 10px rgba(0,0,0,0.05);
}
#api_section {
    background-color: #ffffff;
    border-radius: 8px;
    padding: 1.5rem;
    margin: 1rem 0;
    box-shadow: 0 2px 10px rgba(0,0,0,0.05);
}
#output_section {
    background-color: #d1ecf1;
    border: 1px solid #bee5eb;
    border-radius: 8px;
    padding: 1.5rem;
    margin: 1rem 0;
}
.submit-button {
    background: linear-gradient(45deg, #667eea 0%, #764ba2 100%) !important;
    border: none !important;
    color: white !important;
    padding: 12px 30px !important;
    font-size: 16px !important;
    border-radius: 25px !important;
    margin: 1rem auto !important;
    display: block !important;
    min-width: 200px !important;
}
.submit-button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4) !important;
}
.feature-list {
    display: flex;
    justify-content: space-around;
    flex-wrap: wrap;
    margin: 1rem 0;
}
.feature-item {
    text-align: center;
    padding: 1rem;
    margin: 0.5rem;
    background-color: white;
    border-radius: 8px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
    flex: 1;
    min-width: 200px;
}
#disclaimer {
    background-color: #e8f4f8;
    border: 1px solid #b8daff;
    border-radius: 8px;
    padding: 1rem;
    margin: 1rem 0;
    font-size: 0.9em;
    color: #495057;
}
#disclaimer h4 {
    color: #0056b3;
    margin-top: 0;
}
"""

PROMPT_TEMPLATE = """Please analyze the uploaded course evaluation PDF and extract feedback in the following format:
Instructions:
Extract TWO types of feedback:
1. **Constructive Suggestions** - Rewrite harsh or mean comments into professional, actionable feedback. Focus on the underlying educational concern rather than personal attacks.
2. **Supportive Comments** - Include positive, encouraging, or particularly kind student comments as direct quotes.
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
## Constructive Suggestions for Improvement:
- **[Suggestion theme]** (mentioned by X students) - [Professional rewrite of the core concern]
- **[Another theme]** (mentioned by X students) - [Actionable feedback]  
- **[Individual unique suggestion]** (mentioned by 1 student) - [Specific concern]
## Supportive Student Comments:
> "[Direct quote from positive feedback]"
> "[Another encouraging comment]"  
> "[Specific praise that could be meaningful to instructor]"
## Summary:
- **Most Common Concerns:** List the top 3-4 themes that appeared most frequently
- **Key Strengths Highlighted:** Main positive themes from supportive comments
- **Unique Suggestions:** Any one-off suggestions that might be worth considering
---
PDF Text:
"""

def extract_text_from_pdf(file_path):
    """Extract text from PDF using PyMuPDF"""
    try:
        doc = fitz.open(file_path)
        full_text = ""
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            full_text += page.get_text()
        doc.close()
        return full_text.strip()
    except Exception as e:
        print(f"PyMuPDF extraction error: {e}")
        return ""

def extract_text_via_ocr(file_path):
    """Extract text using OCR for scanned PDFs"""
    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
        
        images = convert_from_bytes(file_bytes)
        text = ""
        for img in images:
            text += pytesseract.image_to_string(img) + "\n"
        return text.strip()
    except Exception as e:
        print(f"OCR extraction error: {e}")
        return ""

def summarize_feedback(pdf_file, api_key, progress=gr.Progress()):
    """Main function to process PDF and generate summary"""
    
    # Validation
    if not pdf_file:
        return "❌ **Error:** No PDF file was uploaded. Please upload a course evaluation PDF."
    
    if not api_key or not api_key.strip():
        return "❌ **Error:** No Claude API key provided. Please enter your API key."
    
    progress(0.1, desc="Reading PDF file...")
    
    try:
        # Get the file path
        file_path = pdf_file.name if hasattr(pdf_file, 'name') else pdf_file
        
        # First try PyMuPDF for text extraction
        progress(0.2, desc="Extracting text from PDF...")
        text = extract_text_from_pdf(file_path)
        
        # If no text found, try OCR
        if not text or len(text.strip()) < 50:
            progress(0.4, desc="Running OCR on scanned PDF...")
            text = extract_text_via_ocr(file_path)
        
        if not text or len(text.strip()) < 10:
            return "❌ **Error:** No extractable text found in this PDF. The file may be corrupted, blank, or too low resolution for OCR."
        
        progress(0.6, desc="Sending to Claude for analysis...")
        
        # Initialize Claude client
        try:
            client = anthropic.Anthropic(api_key=api_key.strip())
        except Exception as e:
            return f"❌ **Error:** Failed to initialize Claude client. Please check your API key. Details: {str(e)}"
        
        # Process text in chunks if too large
        max_chunk_size = 15000
        chunks = []
        
        if len(text) > max_chunk_size:
            # Split into chunks
            words = text.split()
            current_chunk = []
            current_length = 0
            
            for word in words:
                if current_length + len(word) > max_chunk_size and current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = []
                    current_length = 0
                current_chunk.append(word)
                current_length += len(word) + 1
            
            if current_chunk:
                chunks.append(" ".join(current_chunk))
        else:
            chunks = [text]
        
        progress(0.7, desc="Processing with Claude...")
        
        # Process each chunk
        results = []
        
        # List of models to try (in order of preference) - Updated for Claude 4
        models_to_try = [
            "claude-sonnet-4-20250514",  # Claude Sonnet 4 - Primary choice
            "claude-3-5-sonnet-20241022", # Fallback to 3.5 if needed
            "claude-3-5-sonnet-20240620", 
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307"
        ]
        
        model_to_use = None
        
        for i, chunk in enumerate(chunks):
            try:
                progress(0.7 + (0.25 * (i + 1) / len(chunks)), desc=f"Processing chunk {i + 1} of {len(chunks)}...")
                
                # If we haven't determined which model to use, try them in order
                if model_to_use is None:
                    for model in models_to_try:
                        try:
                            response = client.messages.create(
                                model=model,
                                max_tokens=4000,  # Increased for Claude 4
                                temperature=0.2,
                                messages=[{
                                    "role": "user", 
                                    "content": PROMPT_TEMPLATE + chunk
                                }]
                            )
                            model_to_use = model  # This model works, use it for remaining chunks
                            break
                        except Exception as model_error:
                            if "not_found" in str(model_error).lower():
                                continue  # Try next model
                            else:
                                raise model_error  # Different error, re-raise it
                    
                    if model_to_use is None:
                        return "❌ **Error:** Unable to find a compatible Claude model. Please check your API key has access to Claude models."
                
                else:
                    # Use the model that worked before
                    response = client.messages.create(
                        model=model_to_use,
                        max_tokens=4000,
                        temperature=0.2,
                        messages=[{
                            "role": "user", 
                            "content": PROMPT_TEMPLATE + chunk
                        }]
                    )
                
                if response.content and len(response.content) > 0:
                    result_text = response.content[0].text.strip()
                    if i == 0:  # Add model info to first result
                        result_text = f"*Using model: {model_to_use}*\n\n" + result_text
                    results.append(result_text)
                else:
                    results.append("No response generated for this chunk.")
                    
            except Exception as e:
                error_msg = str(e)
                if "rate_limit" in error_msg.lower():
                    results.append(f"⚠️ **Rate limit reached** for chunk {i+1}. Please wait a moment and try again.")
                elif "invalid" in error_msg.lower() and "api" in error_msg.lower():
                    return f"❌ **Error:** Invalid API key. Please check your Claude API key."
                elif "not_found" in error_msg.lower():
                    return f"❌ **Error:** Model not found. Your API key may not have access to Claude models."
                else:
                    results.append(f"❌ **Error processing chunk {i+1}:** {error_msg}")
        
        progress(1.0, desc="Complete!")
        
        # Combine and synthesize results
        if len(results) == 1:
            final_result = results[0]
        else:
            # For multiple chunks, we need to synthesize into one cohesive report
            progress(1.0, desc="Synthesizing final report...")
            
            # Combine all chunk results for final synthesis
            combined_chunks = "\n\n---\n\n".join(results)
            
            synthesis_prompt = """You have received analysis of a course evaluation that was processed in multiple chunks. Please synthesize these chunk analyses into ONE cohesive, professional report that eliminates redundancy and combines similar themes.
INSTRUCTIONS:
1. Merge similar constructive suggestions and combine their frequency counts
2. Remove duplicate supportive comments, keeping the most impactful ones
3. Create one unified summary section
4. Maintain the same professional format but as a single, cohesive analysis
Here are the individual chunk analyses to synthesize:
""" + combined_chunks

            try:
                synthesis_response = client.messages.create(
                    model=model_to_use,
                    max_tokens=5000,  # Increased for synthesis
                    temperature=0.1,  # Lower temperature for more consistent synthesis
                    messages=[{
                        "role": "user", 
                        "content": synthesis_prompt
                    }]
                )
                
                if synthesis_response.content and len(synthesis_response.content) > 0:
                    final_result = synthesis_response.content[0].text.strip()
                    # Add model info
                    final_result = f"*Using model: {model_to_use}*\n\n" + final_result
                else:
                    # Fallback to combined results if synthesis fails
                    final_result = "# Course Evaluation Analysis\n\n"
                    for i, result in enumerate(results, 1):
                        final_result += f"## Analysis Part {i}\n\n{result}\n\n---\n\n"
                    
            except Exception as synthesis_error:
                # If synthesis fails, fall back to the original multi-part format
                final_result = "# Course Evaluation Analysis\n\n"
                final_result += f"*Using model: {model_to_use}*\n\n"
                for i, result in enumerate(results, 1):
                    final_result += f"## Analysis Part {i}\n\n{result}\n\n---\n\n"
                final_result += f"\n\n*Note: Could not synthesize chunks due to: {str(synthesis_error)}*"
        
        # Add metadata
        word_count = len(text.split())
        final_result += f"\n\n---\n**Processing Info:** Analyzed {word_count:,} words from PDF using {len(chunks)} chunk(s)."
        
        return final_result
        
    except Exception as e:
        return f"❌ **Unexpected Error:** {str(e)}\n\nPlease try again or contact support if the issue persists."

# Create the interface
def create_interface():
    with gr.Blocks(css=custom_css, theme=gr.themes.Soft()) as interface:
        
        # Header
        gr.HTML("""
        <div id="title">
            <h1>📋 Distill</h1>
            <p style="font-size: 1.2em; margin: 0;">Transform Course Evaluations into Actionable Insights</p>
        </div>
        """)
        
        gr.HTML("""
        <div id="description">
            <p>Distill automatically extracts and summarizes student feedback from course evaluation PDFs, 
            converting harsh criticism into constructive suggestions while highlighting positive comments.</p>
            <div class="feature-list">
                <div class="feature-item">
                    <strong>📄 Smart PDF Processing</strong><br>
                    Handles both typed and scanned documents
                </div>
                <div class="feature-item">
                    <strong>🤖 AI Analysis</strong><br>
                    Uses Claude 4 to categorize and improve feedback
                </div>
                <div class="feature-item">
                    <strong>✨ Professional Output</strong><br>
                    Converts harsh comments to actionable insights
                </div>
            </div>
        </div>
        """)
        
        # Data Storage Disclaimer
        gr.HTML("""
        <div id="disclaimer">
            <h4>🔒 Data Privacy & Storage Notice</h4>
            <p><strong>Your data security is our priority.</strong> Please be aware of how your course evaluation data is handled:</p>
            <ul>
                <li><strong>API Processing:</strong> Your PDF content is sent to Anthropic's Claude API for analysis</li>
                <li><strong>Automatic Deletion:</strong> Anthropic automatically deletes API inputs and outputs within 30 days</li>
                <li><strong>No Local Storage:</strong> Distill does not store your files or API keys locally</li>
                <li><strong>No Training Use:</strong> Your data is not used to train AI models unless you explicitly opt in</li>
                <li><strong>Usage Policy:</strong> Content flagged as violating Anthropic's usage policy may be retained for up to 2 years</li>
            </ul>
            <p>For complete details, see <a href="https://privacy.anthropic.com/" target="_blank">Anthropic's Privacy Policy</a> and <a href="https://trust.anthropic.com/" target="_blank">Trust Center</a>.</p>
        </div>
        """)
        
        with gr.Row():
            with gr.Column(scale=1):
                pdf_input = gr.File(
                    label="📄 Upload Course Evaluation PDF",
                    file_types=[".pdf"],
                    file_count="single"
                )
                
                gr.HTML("<br>")
                
                gr.HTML("<strong>🔐 Claude API Key Required</strong>")
                api_key_input = gr.Textbox(
                    label="Claude API Key",
                    placeholder="Enter your Claude API key (sk-ant-...)",
                    type="password",
                    lines=1
                )
                gr.HTML("""
                <small style="color: #666;">
                Get your API key from <a href="https://console.anthropic.com/" target="_blank">console.anthropic.com</a>
                </small>
                """)
        
        # Submit button
        submit_btn = gr.Button(
            "🚀 Analyze Feedback",
            variant="primary",
            elem_classes=["submit-button"]
        )
        
        # Output section
        output = gr.Markdown(
            label="📊 Analysis Results",
            value="Upload a PDF and enter your API key to begin analysis..."
        )
        
        # Connect the function
        submit_btn.click(
            fn=summarize_feedback,
            inputs=[pdf_input, api_key_input],
            outputs=output,
            show_progress=True
        )
        
        # Footer
        gr.HTML("""
        <div style="text-align: center; margin-top: 2rem; padding: 1rem; border-top: 1px solid #eee;">
            <p style="color: #666; font-size: 0.9em;">
                Built with ❤️ using Gradio and Claude 4 | 
                <a href="https://github.com/anthropics/anthropic-sdk-python" target="_blank">Learn more about Claude</a> |
                <a href="https://privacy.anthropic.com/" target="_blank">Privacy Policy</a>
            </p>
        </div>
        """)
    
    return interface

if __name__ == "__main__":
    iface = create_interface()
    iface.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False
    )
