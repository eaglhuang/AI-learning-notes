'use strict'

const express = require('express')
const multer = require('multer')
const path = require('path')
const fs = require('fs')

const app = express()
const PORT = process.env.PORT || 3000

// Directories
const ARTICLES_DIR = path.join(__dirname, 'articles')
const METADATA_FILE = path.join(__dirname, 'articles-metadata.json')

// Ensure articles directory exists
if (!fs.existsSync(ARTICLES_DIR)) {
  fs.mkdirSync(ARTICLES_DIR, { recursive: true })
}

// Load or initialise metadata
function loadMetadata () {
  if (fs.existsSync(METADATA_FILE)) {
    try {
      return JSON.parse(fs.readFileSync(METADATA_FILE, 'utf8'))
    } catch {
      return []
    }
  }
  return []
}

function saveMetadata (data) {
  fs.writeFileSync(METADATA_FILE, JSON.stringify(data, null, 2), 'utf8')
}

// Multer storage – only accept .html files
const storage = multer.diskStorage({
  destination (req, file, cb) {
    cb(null, ARTICLES_DIR)
  },
  filename (req, file, cb) {
    // Sanitise original name and prepend timestamp to avoid collisions
    const safe = file.originalname.replace(/[^a-zA-Z0-9._-]/g, '_')
    const unique = `${Date.now()}-${safe}`
    cb(null, unique)
  }
})

function htmlOnlyFilter (req, file, cb) {
  if (path.extname(file.originalname).toLowerCase() === '.html') {
    cb(null, true)
  } else {
    cb(Object.assign(new Error('只允許上傳 .html 格式的檔案'), { status: 400 }))
  }
}

const upload = multer({
  storage,
  fileFilter: htmlOnlyFilter,
  limits: { fileSize: 10 * 1024 * 1024 } // 10 MB
})

// Middleware
app.use(express.json())
app.use(express.static(path.join(__dirname, 'public')))

// ── API ──────────────────────────────────────────────────────────────────────

// GET /api/articles – list all articles
app.get('/api/articles', (req, res) => {
  const metadata = loadMetadata()
  res.json(metadata.slice().reverse()) // newest first
})

// POST /api/articles – upload a new article
app.post('/api/articles', (req, res) => {
  upload.single('article')(req, res, (err) => {
    if (err) {
      const message = err instanceof multer.MulterError
        ? err.message
        : (err.message || 'Upload failed')
      return res.status(400).json({ error: message })
    }

    if (!req.file) {
      return res.status(400).json({ error: 'No file uploaded' })
    }

    const title = (req.body.title || '').trim() || path.basename(req.file.originalname, '.html')
    const description = (req.body.description || '').trim()
    const id = path.basename(req.file.filename, path.extname(req.file.filename))

    const article = {
      id,
      title,
      description,
      filename: req.file.filename,
      originalName: req.file.originalname,
      uploadDate: new Date().toISOString(),
      size: req.file.size
    }

    const metadata = loadMetadata()
    metadata.push(article)
    saveMetadata(metadata)

    res.status(201).json(article)
  })
})

// GET /api/articles/:id – get article metadata
app.get('/api/articles/:id', (req, res) => {
  const metadata = loadMetadata()
  const article = metadata.find(a => a.id === req.params.id)
  if (!article) return res.status(404).json({ error: 'Article not found' })
  res.json(article)
})

// GET /api/articles/:id/content – stream the HTML content
app.get('/api/articles/:id/content', (req, res) => {
  const metadata = loadMetadata()
  const article = metadata.find(a => a.id === req.params.id)
  if (!article) return res.status(404).json({ error: 'Article not found' })

  const filePath = path.join(ARTICLES_DIR, article.filename)
  if (!fs.existsSync(filePath)) {
    return res.status(404).json({ error: 'Article file not found' })
  }

  res.setHeader('Content-Type', 'text/html; charset=utf-8')
  // Prevent the served HTML from being treated as same-origin
  res.setHeader('Content-Security-Policy', "default-src 'self' 'unsafe-inline'")
  res.sendFile(filePath)
})

// DELETE /api/articles/:id – delete an article
app.delete('/api/articles/:id', (req, res) => {
  const metadata = loadMetadata()
  const index = metadata.findIndex(a => a.id === req.params.id)
  if (index === -1) return res.status(404).json({ error: 'Article not found' })

  const article = metadata[index]
  const filePath = path.join(ARTICLES_DIR, article.filename)

  // Remove file
  if (fs.existsSync(filePath)) {
    fs.unlinkSync(filePath)
  }

  // Remove from metadata
  metadata.splice(index, 1)
  saveMetadata(metadata)

  res.json({ message: 'Article deleted' })
})

// ── Start ─────────────────────────────────────────────────────────────────────
app.listen(PORT, () => {
  console.log(`Blog server running at http://localhost:${PORT}`)
})

module.exports = app
