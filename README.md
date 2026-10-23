# 🧠 Recall — Digital Life Organizer

A beautiful, modern personal organizer built with **Python Flask** and **SQLite**. Save notes, links, images, and PDFs — all in one place, fully searchable.

![Recall Screenshot](screenshot.png)

---

## ✨ Features

- 📝 **Notes** — write and save rich text notes
- 🔗 **Links** — bookmark any website URL
- 🖼️ **Images** — upload images (with optional OCR text extraction)
- 📄 **PDFs** — upload PDFs with automatic text extraction
- 🔍 **Search** — keyword search across titles, descriptions, tags & content
- ⭐ **Favourites** — star important items for quick access
- 🗂️ **Categories** — organize items into custom categories
- 🏷️ **Tags** — add comma-separated tags to every item
- ✏️ **Edit & Delete** — full CRUD for all items
- 📊 **Dashboard** — stats, recent items, categories at a glance

---

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.8 or newer ([download](https://python.org))
- pip (already installed if you followed the project setup)

### 2. Install Dependencies

Open a terminal in this folder and run:

```bash
pip install flask
```

### 3. Run the Application

```bash
python app.py
```

Then open your browser and go to:

```
http://127.0.0.1:5000
```

That's it! The database (`recall.db`) is created automatically on first run.

---

## 📁 Project Structure

```
Organizer/
├── app.py              ← Main Flask application
├── recall.db           ← SQLite database (auto-created)
├── requirements.txt    ← Python dependencies
├── README.md           ← This file
├── uploads/            ← Uploaded images & PDFs
├── templates/
│   ├── base.html       ← Shared layout (sidebar, topbar)
│   ├── index.html      ← Dashboard
│   ├── items.html      ← Browse/search all items
│   ├── add.html        ← Add new item form
│   ├── view.html       ← View item detail
│   ├── edit.html       ← Edit item form
│   └── _item_card.html ← Reusable card partial
└── static/
    ├── css/style.css   ← All styles
    └── js/main.js      ← All JavaScript
```

---

## 🔧 Optional Features

### PDF Text Extraction

Install **PyMuPDF** to automatically extract text from uploaded PDFs:

```bash
pip install pymupdf
```

### Image OCR (Text from Images)

1. Install [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) for your OS
2. Install the Python wrapper:
   ```bash
   pip install pillow pytesseract
   ```

The app gracefully handles missing optional libraries — core features always work.

---

## 💡 Tips

- Use the **sidebar search** to quickly find any saved item
- Click the **⭐ star** on any card to toggle favourite status
- Use **categories** to group related items (e.g., Work, Research, Personal)
- Tags make items easier to find — add `#tags` and search for them
- On mobile, tap the **☰ menu** button to open the sidebar

---

## 🛠️ Troubleshooting

| Problem | Solution |
|---------|----------|
| `python app.py` not found | Make sure you're in the `Organizer` folder |
| Port 5000 in use | Change `port=5000` in `app.py` to e.g. `5001` |
| Uploads not showing | Check the `uploads/` folder exists |
| OCR not working | Tesseract must be installed & on your PATH |

---

## 📜 License

Free to use for personal projects.
