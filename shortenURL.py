import streamlit as st
import sqlite3
import random
import string
import hashlib
from datetime import datetime, timedelta, timezone

DB_NAME = "shortlinks.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS links (
            code TEXT PRIMARY KEY,
            long_url TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            max_clicks INTEGER,
            click_count INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_current_utc():
    return datetime.now(timezone.utc)

def generate_short_code(long_url: str, length: int = 6) -> str:
    chars = string.ascii_letters + string.digits
    for _ in range(3):
        code = ''.join(random.choice(chars) for _ in range(length))
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT code FROM links WHERE code = ?", (code,))
        exists = c.fetchone()
        conn.close()
        if not exists:
            return code
    return hashlib.blake2b(long_url.encode(), digest_size=length//2).hexdigest()[:length]

def store_link(code: str, long_url: str, expiry_hours: float, max_clicks: int):
    expires_at = None
    if expiry_hours > 0:
        expires_at = (get_current_utc() + timedelta(hours=expiry_hours)).isoformat()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        INSERT INTO links (code, long_url, created_at, expires_at, max_clicks, click_count)
        VALUES (?, ?, ?, ?, ?, 0)
    ''', (code, long_url, get_current_utc().isoformat(), expires_at, max_clicks))
    conn.commit()
    conn.close()

def get_link_info(code: str):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT long_url, expires_at, max_clicks, click_count FROM links WHERE code = ?", (code,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "long_url": row[0],
            "expires_at": datetime.fromisoformat(row[1]) if row[1] else None,
            "max_clicks": row[2],
            "click_count": row[3]
        }
    return None

def increment_click_count(code: str):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE links SET click_count = click_count + 1 WHERE code = ?", (code,))
    conn.commit()
    conn.close()

def cleanup_expired_links():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = get_current_utc().isoformat()
    c.execute("DELETE FROM links WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
    c.execute("DELETE FROM links WHERE max_clicks > 0 AND click_count >= max_clicks")
    conn.commit()
    conn.close()

def perform_redirect():
    query_params = st.query_params
    if "code" in query_params:
        code = query_params["code"]
        info = get_link_info(code)
        if info is None:
            st.error("❌ Invalid, expired, or used‑up short link.")
            st.stop()
        if info["expires_at"] and datetime.now(timezone.utc) > info["expires_at"]:
            st.error("⏰ This short link has expired.")
            conn = sqlite3.connect(DB_NAME)
            conn.execute("DELETE FROM links WHERE code = ?", (code,))
            conn.commit()
            conn.close()
            st.stop()
        if info["max_clicks"] > 0 and info["click_count"] >= info["max_clicks"]:
            st.error("🔁 This short link has reached its click limit.")
            st.stop()
        increment_click_count(code)
        st.markdown(
            f"""
            <meta http-equiv="refresh" content="0; url={info['long_url']}" />
            <script>window.location.href = "{info['long_url']}";</script>
            Redirecting...
            """,
            unsafe_allow_html=True
        )
        st.stop()

def main():
    st.set_page_config(page_title="Temporary URL Shortener", page_icon="🔗")
    perform_redirect()
    cleanup_expired_links()
    
    st.title("🔗 Temporary URL Shortener")
    st.markdown("Create short links that **self‑destruct** after a time limit or number of clicks.")
    
    # --- FORM for creating short links ---
    with st.form("create_short_link"):
        long_url = st.text_input("Long URL (file download link)", 
                                 placeholder="https://your-server.com/long/path/file.zip?token=secret")
        col1, col2 = st.columns(2)
        with col1:
            expiry_hours = st.number_input("Expiry (hours)", min_value=0.0, value=24.0, step=1.0)
        with col2:
            max_clicks = st.number_input("Max clicks", min_value=1, value=10)
        
        submitted = st.form_submit_button("✨ Generate Short Link")
    
    # --- Handle form submission OUTSIDE the form ---
    if submitted and long_url.strip():
        if not (long_url.startswith("http://") or long_url.startswith("https://")):
            st.warning("URL must start with http:// or https://")
        else:
            code = generate_short_code(long_url)
            store_link(code, long_url, expiry_hours, max_clicks)
            
            st.success("✅ Short link created!")
            
            # Display short code
            st.markdown(f"**Short code:** `{code}`")
            
            # Build the full URL
            server_addr = st.get_option('browser.serverAddress')
            server_port = st.get_option('browser.serverPort')
            full_url = f"http://{server_addr}:{server_port}/?code={code}"
            
            # Display the full URL in a text input (easily selectable and copyable)
            st.markdown("### Share this link:")
            
            # Method 1: Text input that users can select and copy manually
            st.text_input(
                "Full short URL (select all and copy with Ctrl+C):", 
                value=full_url,
                key=f"url_display_{code}",
                disabled=False  # Make it selectable
            )
            
            # Method 2: Code block with copy button (Streamlit native)
            st.markdown("**Or click the copy button below:**")
            st.code(full_url, language="text")
            
            # Method 3: Simple markdown with manual copy instruction
            st.markdown(f"**Direct link:** `{full_url}`")
            
            # Also show for network sharing
            if server_addr != "localhost":
                st.info(f"**Network access:** `http://{server_addr}:{server_port}/?code={code}`")
            
            st.info(f"⏱️ Expires after {expiry_hours} hours OR {max_clicks} clicks")
            
            # Test link section
            st.markdown("---")
            st.markdown("### 🧪 Test Your Short Link")
            st.markdown(f"Click this link to test (will count as one click):")
            st.markdown(f"[{full_url}]({full_url})")
    
    # --- Display active links ---
    with st.expander("📋 Active short links"):
        conn = sqlite3.connect(DB_NAME)
        rows = conn.execute("SELECT code, long_url, expires_at, max_clicks, click_count FROM links ORDER BY created_at DESC LIMIT 20").fetchall()
        conn.close()
        if rows:
            for row in rows:
                code, long_url, expires_at, max_clicks, clicks = row
                server_addr = st.get_option('browser.serverAddress')
                server_port = st.get_option('browser.serverPort')
                test_url = f"http://{server_addr}:{server_port}/?code={code}"
                st.markdown(f"**{code}** → `{long_url[:60]}...`  \n_Expires: {expires_at or 'never'}, Clicks: {clicks}/{max_clicks if max_clicks else '∞'}_  \n🔗 [{test_url}]({test_url})")
        else:
            st.write("No active links.")

if __name__ == "__main__":
    main()