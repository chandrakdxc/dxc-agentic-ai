from pathlib import Path
import sys

# Add the lab root first so this standalone app can import the shared AWS helpers.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import hashlib
import json
from datetime import date
from io import BytesIO

import numpy as np
import streamlit as st
from pypdf import PdfReader
from askit_core import bedrock, config

AVATAR = "🧑‍💻"

# Set a dark teal page so the upload, index, and chat live in one clear workspace.
st.set_page_config(page_title="MY FIRST RAG", page_icon=AVATAR, layout="centered")
st.markdown(
    """<style>
    .stApp { background: #071c1c; color: #e5f4f1; } .hero { background: #0d4845;
        border: 1px solid #167b73; border-radius: 12px; padding: 18px 22px; margin-bottom: 18px; }
    .hero h1 { color: #f2fffc; margin: 0; } .hero p { color: #8fe3d5; margin: 4px 0 0; }
    .stChatMessage { background: #102c2b; border: 1px solid #1b4946; border-radius: 12px; }
    .stButton > button, .stDownloadButton > button { background: #087f75; color: white; border: 0; border-radius: 8px; }
    .stButton > button:hover, .stDownloadButton > button:hover { background: #0ca696; color: white; }
    .badge { color: #062b27; background: #8fe3d5; padding: 3px 9px; border-radius: 20px; }
    .weak { color: #342100; background: #ffd27a; } .about { background: #102c2b;
        border-left: 3px solid #12a997; padding: 12px; border-radius: 8px; }
    </style>""",
    unsafe_allow_html=True,
)
st.markdown('<div class="hero"><h1>MY FIRST RAG</h1><p>Upload.Ask.Done</p></div>', unsafe_allow_html=True)

# Keep each chunk tied to its PDF page so answers can cite their evidence.
def chunk_pages(page_texts, chunk_size, overlap):
    chunks = []
    step = chunk_size - overlap
    for page_number, text in page_texts:
        words = text.split()
        for start in range(0, len(words), step):
            piece = " ".join(words[start : start + chunk_size]).strip()
            if piece:
                chunks.append({"page": page_number, "text": piece})
    return chunks

# Make one Titan request per text; the build loop stays within the shared-account limit.
def embed_text(text):
    response = bedrock.client().invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        body=json.dumps({"inputText": text, "dimensions": 512, "normalize": True}),
        accept="application/json",
        contentType="application/json",
    )
    return np.array(json.loads(response["body"].read())["embedding"], dtype=float)

def cosine_similarity(left, right):
    denominator = np.linalg.norm(left) * np.linalg.norm(right)
    return float(np.dot(left, right) / denominator) if denominator else 0.0

# Retrieve relevant evidence and ask Nova to answer briefly in the requested voice.
def answer_question(question):
    query_vector = embed_text(question)
    scores = [cosine_similarity(query_vector, vector) for vector in st.session_state.vectors]
    best_indexes = np.argsort(scores)[::-1][: st.session_state.top_k]
    sources = [{**st.session_state.chunks[index], "score": scores[index]} for index in best_indexes]
    context = "\n\n".join(f"[p.{item['page']}] {item['text']}" for item in sources)
    prompt = (
        "Answer ONLY from the context. If the answer is not in the context, say you could not "
        "find it in the PDF. Cite the page like [p.3]. Be a concise FDEengineer: practical, "
        "direct, and short. The answer must still use only the PDF and cite pages.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}"
    )
    response = bedrock.client().converse(
        modelId=config.SMALL_MODEL,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 500, "temperature": 0.2},
    )
    answer = response["output"]["message"]["content"][0]["text"]
    return answer, sources

# Store the user question before calling AWS so a failed request can be retried.
def run_pending_question():
    try:
        answer, sources = answer_question(st.session_state.pending_question)
        best_score = sources[0]["score"] if sources else 0.0
        st.session_state.messages.append({"role": "assistant", "content": answer,
                                          "sources": sources, "best_score": best_score})
        st.session_state.pending_question = ""
        st.session_state.last_error = ""
    except Exception:
        st.session_state.last_error = (
            "AWS request failed. Check your .env keys, AWS region, and Titan model access, then retry."
        )

# Initialize session data once, and keep controls in the sidebar away from the conversation.
for key, value in {"upload_hash": None, "chunks": [], "vectors": [], "messages": [],
                   "index_settings": None, "index_pages": 0, "pending_question": "", "last_error": ""}.items():
    if key not in st.session_state:
        st.session_state[key] = value

with st.sidebar:
    st.subheader("Settings")
    st.session_state.top_k = st.slider("Top-K", 1, 6, 3)
    chunk_size = st.slider("Chunk size (words)", 60, 300, 120, step=10)
    overlap = st.slider("Overlap (words)", 0, 50, 30, step=5)
    about = f'<div class="about"><b>About me</b><br>CHANDRA<br>{date.today().isoformat()}<br>Powered by curiosity and chai.</div>'
    st.markdown(about, unsafe_allow_html=True)
    if st.button("Clear chat", use_container_width=True):
        st.session_state.messages, st.session_state.pending_question, st.session_state.last_error = [], "", ""
    if st.session_state.messages:
        markdown_chat = "\n\n".join(
            f"## {'You' if item['role'] == 'user' else 'MY FIRST RAG'}\n{item['content']}"
            for item in st.session_state.messages
        )
        st.download_button("Download chat (.md)", markdown_chat, "chat.md", "text/markdown")

# Detect replacement uploads and discard the previous document and its conversation.
uploaded_file = st.file_uploader("Upload a PDF", type="pdf")
pdf_bytes = uploaded_file.getvalue() if uploaded_file else None
current_hash = hashlib.sha256(pdf_bytes).hexdigest() if pdf_bytes is not None else None
if current_hash != st.session_state.upload_hash:
    st.session_state.upload_hash = current_hash
    st.session_state.chunks, st.session_state.vectors, st.session_state.messages = [], [], []
    st.session_state.index_settings, st.session_state.index_pages = None, 0
    st.session_state.pending_question, st.session_state.last_error = "", ""

settings = (chunk_size, overlap)
# Build only on request, and publish the index only after every chunk has an embedding.
if uploaded_file:
    if st.button("Build index", type="primary", use_container_width=True):
        try:
            reader = PdfReader(BytesIO(pdf_bytes))
            page_texts = [(number, page.extract_text() or "") for number, page in enumerate(reader.pages, start=1)]
        except Exception:
            st.error("I could not read that PDF. Please try another PDF file.")
            page_texts = None
        if page_texts is not None:
            chunks = chunk_pages(page_texts, chunk_size, overlap)
            if not chunks:
                st.warning("This PDF has no selectable text. It may be scanned; try a text-based PDF.")
                st.session_state.chunks = []
                st.session_state.vectors = []
                st.session_state.index_settings = None
            else:
                progress = st.progress(0, text="Building your index...")
                vectors = []
                try:
                    for number, chunk in enumerate(chunks, start=1):
                        vectors.append(embed_text(chunk["text"]))
                        progress.progress(number / len(chunks), text=f"Embedding {number} of {len(chunks)}")
                    st.session_state.chunks, st.session_state.vectors = chunks, vectors
                    st.session_state.index_settings = settings
                    st.session_state.index_pages = len(reader.pages)
                except Exception:
                    st.error("AWS request failed. Check your .env keys, AWS region, and Titan model access, then retry.")
    if st.session_state.index_settings == settings and st.session_state.chunks:
        st.success(f"Indexed {st.session_state.index_pages} pages and {len(st.session_state.chunks)} chunks.")
    elif st.session_state.chunks:
        st.info("Chunk settings changed. Select Build index to rebuild before chatting.")

ready = bool(st.session_state.chunks) and st.session_state.index_settings == settings
# Re-render stored turns on each rerun so chat survives controls and button clicks.
if ready:
    for item in st.session_state.messages:
        with st.chat_message(item["role"], avatar=AVATAR if item["role"] == "assistant" else None):
            st.markdown(item["content"])
            if item["role"] == "assistant":
                badge = "grounded" if item["best_score"] >= 0.35 else "weak match"
                style = "badge" if badge == "grounded" else "badge weak"
                st.markdown(f'<span class="{style}">{badge}</span>', unsafe_allow_html=True)
                with st.expander("Sources"):
                    for source in item["sources"]:
                        st.markdown(f"**[p.{source['page']}] · {source['score']:.2f}**")
                        st.write(source["text"])
    if st.session_state.last_error:
        st.error(st.session_state.last_error)
        if st.button("Retry last question"):
            run_pending_question()
            st.rerun()
    if st.button("Not in my PDF?", help="Ask a sample question that should not be answered from this document."):
        st.session_state.messages.append({"role": "user", "content": "Who won the last cricket world cup?"})
        st.session_state.pending_question = "Who won the last cricket world cup?"
        run_pending_question()
        st.rerun()
    question = st.chat_input("Ask a question about your PDF")
    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        st.session_state.pending_question = question
        st.session_state.last_error = ""
        run_pending_question()
        st.rerun()
elif uploaded_file and st.session_state.chunks:
    st.caption("Rebuild the index with the selected chunk settings to continue.")

st.markdown("<div style='text-align:center;color:#8caeaa;padding:22px'>Built by CHANDRA with vibe coding at DevPro Academy</div>", unsafe_allow_html=True)
