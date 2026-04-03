import streamlit as st
import sqlite3
import random
import string
import hashlib
from datetime import datetime, timedelta, timezone

# Database setup
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
            Redirecting to your file...
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
    
    # Session state to store generated links
    if 'generated_short_code' not in st.session_state:
        st.session_state.generated_short_code = None
    if 'generated_expiry' not in st.session_state:
        st.session_state.generated_expiry = None
    if 'generated_clicks' not in st.session_state:
        st.session_state.generated_clicks = None
    
    # --- Form for creating short links ---
    with st.form("create_short_link"):
        long_url = st.text_input(
            "Long URL (the file or page you want to share)", 
            placeholder="https://drive.google.com/your-secret-file.zip?dl=1",
            help="This URL will be hidden from recipients"
        )
        
        col1, col2 = st.columns(2)
        with col1:
            expiry_hours = st.number_input(
                "Expiry (hours)", 
                min_value=0.0, 
                value=24.0, 
                step=1.0,
                help="0 = never expires (but click limit still applies)"
            )
        with col2:
            max_clicks = st.number_input(
                "Max clicks", 
                min_value=1, 
                value=10,
                help="Link becomes invalid after this many uses"
            )
        
        submitted = st.form_submit_button("✨ Generate Short Link", use_container_width=True)
    
    # --- Handle form submission ---
    if submitted and long_url.strip():
        if not (long_url.startswith("http://") or long_url.startswith("https://")):
            st.warning("⚠️ URL must start with http:// or https://")
        else:
            # Generate and store the short link
            code = generate_short_code(long_url)
            store_link(code, long_url, expiry_hours, max_clicks)
            
            # Store in session state
            st.session_state.generated_short_code = code
            st.session_state.generated_expiry = expiry_hours
            st.session_state.generated_clicks = max_clicks
            
            st.success("✅ Short link created successfully!")
            st.rerun()
    
    # Display the generated short link if it exists
    if st.session_state.generated_short_code:
        code = st.session_state.generated_short_code
        
        st.markdown("---")
        st.markdown("## 🔗 Your Short Link Is Ready!")
        st.markdown("**The original long URL is completely hidden from recipients**")
        
        # Display the short code prominently
        st.markdown("### Short Code:")
        st.markdown(f"# `{code}`")
        
        # Method 1: st.code with built-in copy button (THIS WORKS!)
        st.markdown("### 📋 Copy this entire URL:")
        full_short_url = f"?code={code}"
        st.code(full_short_url, language="text")
        st.caption("💡 **Click the copy icon (📋) in the top-right corner of the box above**")
        
        # Method 2: Text input for manual selection
        st.markdown("### Or manually copy:")
        st.text_input(
            "Select all text below and press Ctrl+C (or Cmd+C on Mac):",
            value=full_short_url,
            key="manual_copy_url",
            disabled=False
        )
        
        # Method 3: Display as clickable link
        st.markdown("### Preview (click to test):")
        st.markdown(f"[{full_short_url}]({full_short_url})")
        
        # Show what the full URL will look like when deployed
        st.info(f"""
        **📌 When deployed on Streamlit Cloud, the full URL will be:**
https://your-app.streamlit.app/?code={code}

text

**📊 Link Details:**
- **Short Code:** `{code}`
- **Expires:** {st.session_state.generated_expiry} hours {'(never)' if st.session_state.generated_expiry == 0 else ''}
- **Max Clicks:** {st.session_state.generated_clicks}
- **Original URL is completely hidden** from recipients
""")

# Reset button
col_reset1, col_reset2, col_reset3 = st.columns([1, 2, 1])
with col_reset2:
    if st.button("🔄 Create Another Short Link", use_container_width=True):
        st.session_state.generated_short_code = None
        st.rerun()

st.markdown("---")

# --- Display active links for management ---
with st.expander("📋 Manage Active Short Links", expanded=False):
conn = sqlite3.connect(DB_NAME)
rows = conn.execute("SELECT code, long_url, expires_at, max_clicks, click_count, created_at FROM links ORDER BY created_at DESC LIMIT 50").fetchall()
conn.close()

if rows:
    for row in rows:
        code, long_url, expires_at, max_clicks, clicks, created_at = row
        
        with st.container():
            col1, col2, col3 = st.columns([3, 1, 1])
            
            with col1:
                st.markdown(f"**Code:** `{code}`")
                st.caption(f"Original: `{long_url[:60]}...`")
                st.caption(f"Clicks: {clicks}/{max_clicks} | Expires: {expires_at[:10] if expires_at else 'Never'}")
            
            with col2:
                # Copy button for this specific link using st.code
                if st.button(f"📋 Get Link", key=f"get_{code}"):
                    st.code(f"?code={code}", language="text")
                    st.info(f"**Copy the URL above** (click the 📋 icon)")
            
            with col3:
                if st.button(f"🗑️ Delete", key=f"del_{code}"):
                    conn = sqlite3.connect(DB_NAME)
                    conn.execute("DELETE FROM links WHERE code = ?", (code,))
                    conn.commit()
                    conn.close()
                    st.rerun()
            
            st.markdown("---")
else:
    st.info("No active short links yet. Create your first one above!")

# Footer with instructions
st.markdown("---")
st.markdown("### 📖 Quick Start Guide:")
col1, col2, col3 = st.columns(3)
with col1:
st.markdown("**1️⃣ Create**")
st.markdown("Enter your long URL and set expiry/clicks")
with col2:
st.markdown("**2️⃣ Copy**")
st.markdown("Click the 📋 icon in the code box")
with col3:
st.markdown("**3️⃣ Share**")
st.markdown("Send the short link to others")

st.caption("🔒 Your original long URLs are never exposed to recipients. Links self-destruct automatically.")

if __name__ == "__main__":
main()
