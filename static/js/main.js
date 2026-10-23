// ── Always serve fresh data on back/forward navigation (no manual refresh needed) ──
window.addEventListener('pageshow', function(event) {
  if (event.persisted) {
    window.location.reload();
  }
});

// ── Global JS ─────────────────────────────────────────────────────────────────

// Mobile sidebar toggle
const sidebar    = document.getElementById('sidebar');
const menuBtn    = document.getElementById('mobileMenuBtn');
const overlay    = document.getElementById('sidebarOverlay');

if (menuBtn) {
  menuBtn.addEventListener('click', () => {
    sidebar.classList.toggle('open');
    overlay && overlay.classList.toggle('show');
  });
}
if (overlay) {
  overlay.addEventListener('click', () => {
    sidebar.classList.remove('open');
    overlay.classList.remove('show');
  });
}

// ── Live Search in Sidebar ────────────────────────────────────────────────────
const searchInput   = document.getElementById('sidebarSearch');
const searchResults = document.getElementById('search-results-dropdown');

const TYPE_ICONS = { note: '📝', link: '🔗', image: '🖼️', pdf: '📄' };

if (searchInput && searchResults) {
  let debounceTimer;
  searchInput.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    const q = searchInput.value.trim();
    if (!q) { searchResults.style.display = 'none'; return; }
    debounceTimer = setTimeout(async () => {
      try {
        const res  = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        if (!data.length) {
          searchResults.innerHTML = '<a href="#" style="justify-content:center;color:var(--text-muted)">No results found</a>';
        } else {
          searchResults.innerHTML = data.map(item => `
            <a href="/item/${item.id}">
              <span class="sr-icon">${TYPE_ICONS[item.type] || '📌'}</span>
              <span>
                <div class="sr-title">${escapeHTML(item.title)}</div>
                <div class="sr-cat">${escapeHTML(item.category)}${item.subcategory ? ' › ' + escapeHTML(item.subcategory) : ''}</div>
              </span>
            </a>
          `).join('');
        }
        searchResults.style.display = 'block';
      } catch(e) { console.error(e); }
    }, 280);
  });

  document.addEventListener('click', e => {
    if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
      searchResults.style.display = 'none';
    }
  });
  searchInput.addEventListener('keydown', e => {
    if (e.key === 'Escape') { searchResults.style.display = 'none'; searchInput.blur(); }
  });
}

// ── Favourite Star Toggle ─────────────────────────────────────────────────────
document.querySelectorAll('.fav-star').forEach(btn => {
  btn.addEventListener('click', async (e) => {
    e.preventDefault();
    e.stopPropagation();
    const itemId = btn.dataset.itemId;
    try {
      const res  = await fetch(`/item/${itemId}/favourite`, { method: 'POST' });
      const data = await res.json();
      btn.classList.toggle('active', data.favourite === 1);
      btn.textContent = data.favourite ? '⭐' : '☆';
    } catch(err) { console.error(err); }
  });
});

// ── Delete Confirmation Modal ─────────────────────────────────────────────────
const deleteModal   = document.getElementById('deleteModal');
const confirmDelete = document.getElementById('confirmDelete');
const cancelDelete  = document.getElementById('cancelDelete');
let   deleteForm    = null;

document.querySelectorAll('.delete-trigger').forEach(btn => {
  btn.addEventListener('click', (e) => {
    e.preventDefault();
    deleteForm = btn.closest('form') || document.getElementById(btn.dataset.formId);
    if (deleteModal) deleteModal.classList.add('show');
  });
});
if (confirmDelete) confirmDelete.addEventListener('click', () => { if (deleteForm) deleteForm.submit(); });
if (cancelDelete)  cancelDelete.addEventListener('click',  () => { deleteModal.classList.remove('show'); deleteForm = null; });
if (deleteModal)   deleteModal.addEventListener('click', e => { if (e.target === deleteModal) { deleteModal.classList.remove('show'); deleteForm = null; } });

// ── Type Switcher (Add / Edit form) ──────────────────────────────────────────
function initTypeSwitcher() {
  const typeBtns     = document.querySelectorAll('.type-btn');
  const typeSections = document.querySelectorAll('.type-section');
  const typeInput    = document.getElementById('typeInput');

  function switchType(type) {
    typeBtns.forEach(b => b.classList.toggle('active', b.dataset.type === type));
    typeSections.forEach(s => s.classList.toggle('hidden', s.dataset.type !== type));
    if (typeInput) typeInput.value = type;
  }

  typeBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      switchType(btn.dataset.type);
    });
  });
}
document.addEventListener('DOMContentLoaded', initTypeSwitcher);
initTypeSwitcher(); // Run immediately in case DOM is already ready

// ── Image & File Upload Handlers (with Preview) ────────────────────────────────
function initFileUploaders() {
  // 1. Image Uploader
  const imgInput = document.getElementById('imageFileInput') || document.getElementById('fileInput');
  const imgPrev  = document.getElementById('imagePreview');
  const imgPrevCont = document.getElementById('imagePreviewContainer');
  const imgName  = document.getElementById('imageFileName');

  if (imgInput) {
    imgInput.addEventListener('change', function() {
      if (this.files && this.files[0]) {
        const file = this.files[0];
        if (imgPrev && imgPrevCont) {
          const reader = new FileReader();
          reader.onload = function(e) {
            imgPrev.src = e.target.result;
            imgPrevCont.style.display = 'block';
            if (imgName) imgName.textContent = file.name + ' (' + (file.size / 1024).toFixed(1) + ' KB)';
          };
          reader.readAsDataURL(file);
        }
      }
    });
  }

  // 2. PDF Uploader
  const pdfInput = document.getElementById('pdfFileInput');
  const pdfName  = document.getElementById('pdfFileName');
  if (pdfInput && pdfName) {
    pdfInput.addEventListener('change', function() {
      if (this.files && this.files[0]) {
        pdfName.textContent = '📄 Selected: ' + this.files[0].name;
        pdfName.style.display = 'block';
      }
    });
  }

  // Generic Drag & Drop on all .drop-zone elements
  document.querySelectorAll('.drop-zone').forEach(dz => {
    const input = dz.querySelector('input[type="file"]');
    if (!input) return;

    dz.addEventListener('dragover', e => {
      e.preventDefault();
      dz.classList.add('drag-over');
    });
    dz.addEventListener('dragleave', () => dz.classList.remove('drag-over'));
    dz.addEventListener('drop', e => {
      e.preventDefault();
      dz.classList.remove('drag-over');
      if (e.dataTransfer.files.length) {
        input.files = e.dataTransfer.files;
        input.dispatchEvent(new Event('change'));
      }
    });
  });
}
document.addEventListener('DOMContentLoaded', initFileUploaders);
initFileUploaders();

// ── Submit Processing Indicator ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
  const form = document.getElementById('addForm');
  const indicator = document.getElementById('processingIndicator');
  const saveBtn = document.getElementById('saveBtn');
  if (form && indicator) {
    form.addEventListener('submit', function() {
      indicator.style.display = 'block';
      if (saveBtn) {
        // non-blocking submission
        saveBtn.style.pointerEvents = 'none'; saveBtn.style.opacity = '0.75'; saveBtn.innerText = '⏳ Saving & Analyzing...';
      }
    });
  }
});

// ── Flash message auto-dismiss ────────────────────────────────────────────────
document.querySelectorAll('.flash').forEach(el => {
  setTimeout(() => {
    el.style.transition = 'opacity 0.5s';
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 500);
  }, 4000);
});

// ── Auto-grow textarea ────────────────────────────────────────────────────────
document.querySelectorAll('textarea.form-control').forEach(ta => {
  const resize = () => { ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 'px'; };
  ta.addEventListener('input', resize);
  resize();
});

// ── Helpers ───────────────────────────────────────────────────────────────────
function escapeHTML(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}


// ── Google Photos Style Grid Density Controls ─────────────────────────────────
function setGridDensity(size) {
  const grids = document.querySelectorAll('.items-grid');
  grids.forEach(g => {
    g.classList.remove('grid-sm', 'grid-md', 'grid-lg');
    g.classList.add('grid-' + size);
  });

  // Update active state on size buttons
  document.querySelectorAll('.grid-size-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.size === size);
  });

  try {
    localStorage.setItem('recall_grid_density', size);
  } catch(e) {}
}

// Restore user preferred density on load (defaults to 'sm' for compact neat view!)
document.addEventListener('DOMContentLoaded', function() {
  let savedSize = 'sm';
  try {
    savedSize = localStorage.getItem('recall_grid_density') || 'sm';
  } catch(e) {}
  setGridDensity(savedSize);
});

// ── Google Photos Style Lightbox Modal ────────────────────────────────────────
function openImageLightbox(btn) {
  const src = btn.dataset.imgSrc;
  const title = btn.dataset.imgTitle || 'Image View';
  const cat = btn.dataset.imgCat || '';

  const modal = document.getElementById('imageLightboxModal');
  const img = document.getElementById('lightboxImg');
  const titleEl = document.getElementById('lightboxTitle');
  const catEl = document.getElementById('lightboxCategory');

  if (modal && img) {
    img.src = src;
    if (titleEl) titleEl.textContent = title;
    if (catEl) {
      catEl.textContent = cat;
      catEl.style.display = cat ? 'inline-block' : 'none';
    }
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  }
}

function closeImageLightbox() {
  const modal = document.getElementById('imageLightboxModal');
  if (modal) {
    modal.style.display = 'none';
    document.body.style.overflow = '';
  }
}

// Close lightbox on Escape key
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    closeImageLightbox();
  }
});


// ── Global Top Search Bar (Photos, #Tags, AI OCR text) ────────────────────────
function initTopSearch() {
  const topInput = document.getElementById('globalTopSearch');
  const topDropdown = document.getElementById('top-search-dropdown');
  const topForm = document.getElementById('topSearchForm');
  if (!topInput || !topDropdown) return;

  const TYPE_ICONS = { note: '📝', link: '🔗', image: '🖼️', pdf: '📄' };
  let debounceTimer;

  topInput.addEventListener('input', function() {
    clearTimeout(debounceTimer);
    const rawVal = topInput.value.trim();
    if (!rawVal) {
      topDropdown.style.display = 'none';
      return;
    }

    debounceTimer = setTimeout(async function() {
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(rawVal)}`);
        const data = await res.json();
        if (!data.length) {
          topDropdown.innerHTML = `
            <div style="padding:16px;text-align:center;color:var(--text-muted);font-size:13px;">
              🔍 No items matching "<strong>${escapeHTML(rawVal)}</strong>"<br>
              <span style="font-size:11px;color:var(--text-secondary);margin-top:4px;display:block;">Press Enter to search all archives</span>
            </div>
          `;
        } else {
          let html = data.map(item => {
            const isImg = (item.type === 'image' && item.filename);
            const thumbHtml = isImg
              ? `<img src="/uploads/${encodeURIComponent(item.filename)}" class="top-search-thumb" alt="${escapeHTML(item.title)}"/>`
              : `<div class="top-search-icon-box">${TYPE_ICONS[item.type] || '📌'}</div>`;

            // Display matching tags
            let tagsHtml = '';
            if (Array.isArray(item.tags) && item.tags.length) {
              tagsHtml = '<div class="top-search-tags">' +
                item.tags.slice(0, 3).map(t => `<span class="top-search-tag">#${escapeHTML(t)}</span>`).join('') +
                '</div>';
            }

            return `
              <a href="/item/${item.id}" class="top-search-item">
                ${thumbHtml}
                <div class="top-search-details">
                  <div class="top-search-title">${escapeHTML(item.title)}</div>
                  <div class="top-search-meta">
                    <span style="color:var(--accent-purple);font-weight:600;">${escapeHTML(item.category)}</span>
                    ${item.subcategory ? '<span>› ' + escapeHTML(item.subcategory) + '</span>' : ''}
                    ${item.snippet ? '<span style="color:var(--text-muted);">· ' + escapeHTML(item.snippet.slice(0, 45)) + '</span>' : ''}
                  </div>
                  ${tagsHtml}
                </div>
              </a>
            `;
          }).join('');

          html += `
            <a href="/items?q=${encodeURIComponent(rawVal)}" class="top-search-footer">
              See all results for "${escapeHTML(rawVal)}" →
            </a>
          `;
          topDropdown.innerHTML = html;
        }
        topDropdown.style.display = 'block';
      } catch(err) {
        console.error('Top search error:', err);
      }
    }, 200);
  });

  // Close dropdown when clicking outside
  document.addEventListener('click', function(e) {
    if (!topInput.contains(e.target) && !topDropdown.contains(e.target)) {
      topDropdown.style.display = 'none';
    }
  });

  topInput.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      topDropdown.style.display = 'none';
      topInput.blur();
    }
  });

  // Global Keyboard shortcut: press '/' or 'Ctrl+K' to focus search
  document.addEventListener('keydown', function(e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      topInput.focus();
      topInput.select();
    }
  });
}

document.addEventListener('DOMContentLoaded', initTopSearch);
