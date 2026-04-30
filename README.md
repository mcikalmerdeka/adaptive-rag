# Document to Markdown Converter

Convert various document formats (PDF, DOCX, PPTX, XLSX, images, HTML, and more) to clean Markdown using [Docling](https://github.com/docling-project/docling).

This is **Step 1** of the intelligent document processing pipeline — establishing a reliable document-to-markdown conversion layer before chunking and RAG operations.

## Features

- **Multi-format support**: PDF, DOCX, PPTX, XLSX, HTML, Markdown, images (PNG, JPEG, TIFF, BMP, WEBP), CSV, AsciiDoc, XML, JSON
- **File type detection**: Automatic format detection and validation
- **Markdown preview**: Real-time preview of converted markdown
- **Export**: One-click download of the generated `.md` file
- **Clean architecture**: Modular design ready for extension (chunking, embedding, etc.)

## Project Structure

```
.
├── src/
│   ├── core/
│   │   ├── file_detector.py      # File type detection & validation
│   │   └── converter.py           # Docling wrapper for markdown conversion
│   └── app.py                     # Gradio web interface
├── requirements.txt
└── README.md
```

## Installation

1. Create a virtual environment (recommended):

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

> **Note**: Docling will download AI models on first run (OCR, table structure, etc.). This may take a few minutes depending on your connection.

## Usage

Run the Gradio application:

```bash
uv run app.py
```

Then open your browser at `http://localhost:7860`.

### How to use

1. **Upload** a document using the file picker
2. **Convert** by clicking the "Convert to Markdown" button
3. **Preview** the generated markdown in the right panel
4. **Download** the `.md` file using the download button

## Architecture

This application follows a layered architecture designed for future extension:

```
┌─────────────────────────────────────┐
│           Gradio UI (src/app.py)     │
│  - File upload, preview, download    │
├─────────────────────────────────────┤
│      Converter Service               │
│  - Docling wrapper, error handling   │
├─────────────────────────────────────┤
│      File Type Detector              │
│  - Extension/mime detection          │
│  - Supported format validation       │
├─────────────────────────────────────┤
│           Docling Engine             │
│  - PDF, Office, Image parsing        │
│  - Markdown export                   │
└─────────────────────────────────────┘
```

## Next Steps (Future Pipeline)

1. ✅ **Document Converter** (this step) — convert any format to Markdown
2. 🔄 **Chunking** — split markdown into semantically meaningful chunks
3. 🔄 **Embedding** — generate vector embeddings for each chunk
4. 🔄 **Vector Store** — store embeddings for retrieval
5. 🔄 **RAG Query** — retrieve relevant chunks and generate answers

## Dependencies

- [docling](https://github.com/docling-project/docling) — Document parsing and conversion
- [gradio](https://gradio.app) — Web UI framework

## License

MIT
