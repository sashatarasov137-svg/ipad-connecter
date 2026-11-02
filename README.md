# iPad Connecter

Turn your iPad into a pad of shortcut buttons for your Mac.
Tap **Alt 4** on the iPad → your Mac presses Alt+4. Great for games and hard-to-reach combos.

## How it works
- A tiny program runs on your Mac (plain Python, nothing to install).
- Your iPad opens a web page from it over your Wi‑Fi.
- Buttons send key presses over a direct connection — usually just a few milliseconds.
- Holding a button holds the keys down (good for games); letting go releases them.

## Setup (one time)
1. On your Mac, download this repo and open Terminal in its folder.
2. Run:
   ```bash
   python3 connecter.py
   ```
3. Give it permission: **System Settings → Privacy & Security → Accessibility**, turn on **Terminal**. Then stop (Ctrl+C) and run it again.
4. Terminal prints a link like `http://Your-MacBook.local:8765/?k=abc123`. Open it in **Safari on your iPad** (same Wi‑Fi).
5. In Safari tap **Share → Add to Home Screen**. Now it opens full-screen like an app.

## Using it
- Tap **Edit** to add, change or delete buttons. Combos look like `alt+4`, `cmd+c`, `ctrl+shift+t`, `f5`.
- The dot at the top is green when connected, and shows the delay in ms.
- The `?k=...` code in the link is a secret so other people on your Wi‑Fi can't press keys on your Mac. Delete the `.token` file to make a new one.

## Tips
- If the iPad can't connect, try the second link (the number one, like `192.168.1.20`).
- macOS might ask to allow incoming connections for Python — click **Allow**.
