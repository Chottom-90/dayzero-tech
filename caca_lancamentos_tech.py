:root {
  --bg: #0b0d12;
  --surface: #12151c;
  --text: #e6e8eb;
  --text-muted: #9aa1ac;
  --accent: #5b8cff;
  --border: #232732;
  --max-width: 720px;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  padding: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.65;
}

.wrap {
  max-width: var(--max-width);
  margin: 0 auto;
  padding: 48px 20px 80px;
}

/* ---------- Header ---------- */
header.site-header {
  margin-bottom: 40px;
}

header.site-header a.logo {
  font-size: 1.6rem;
  font-weight: 800;
  color: var(--text);
  text-decoration: none;
  letter-spacing: -0.02em;
}

header.site-header a.logo span {
  color: var(--accent);
}

header.site-header p.tagline {
  color: var(--text-muted);
  margin: 6px 0 0;
  font-size: 0.95rem;
}

/* ---------- Post list (index) ---------- */
ul.post-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

ul.post-list li {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
  transition: border-color 0.15s ease, transform 0.15s ease;
}

ul.post-list li:hover {
  border-color: var(--accent);
  transform: translateY(-1px);
}

ul.post-list li a {
  display: block;
  padding: 18px 20px;
  color: var(--text);
  text-decoration: none;
  font-weight: 600;
  font-size: 1.05rem;
}

/* ---------- Article page ---------- */
article h1 {
  font-size: 1.9rem;
  line-height: 1.25;
  margin: 0 0 8px;
  letter-spacing: -0.01em;
}

article > p em {
  color: var(--text-muted);
  font-size: 0.85rem;
  font-style: normal;
}

article h2 {
  font-size: 1.25rem;
  margin: 32px 0 10px;
  color: var(--text);
}

article p {
  margin: 0 0 16px;
  color: var(--text);
}

article ul, article ol {
  margin: 0 0 16px;
  padding-left: 22px;
}

article li {
  margin-bottom: 6px;
}

article a {
  color: var(--accent);
}

article small {
  color: var(--text-muted);
  display: block;
  margin-top: 32px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

/* ---------- Back link ---------- */
.back-link {
  display: inline-block;
  margin-top: 32px;
  color: var(--text-muted);
  text-decoration: none;
  font-size: 0.9rem;
}

.back-link:hover {
  color: var(--accent);
}

/* ---------- Empty state ---------- */
.empty-state {
  color: var(--text-muted);
  font-style: italic;
}
