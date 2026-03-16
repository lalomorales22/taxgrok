# Taxgrok

```text
     █████████████ ██
   ███████████████████        ███                                █████████                        █████
 ██████░░░░░░░░░██████░       ████                             ████████████                       █████░
█████░░░░░░░░██████████░    █████████ █████████  █████  █████ ██████░░░░██░░ ████████  █████████  █████░██████
███░░░░░░░░██████░░░████░   █████████░██████████  ██████████░█████░░░██████░░████████████████████ ███████████░░
███░░░░░░█████░░░░░░████░░   ░████░░░░██████████░  ░██████░░░█████░░░██████░░████░░░░████░░░░████░████████░░░░░░
███░░░░█████░░░░░░░░████░░   ███████░███████████░░ ████████░░░███████░░████░░████░░░░██████░█████░██████████░░░░░
██████████░░░░░░░░░████░░░░   ██████████████████░██████░█████░░████████████░░████░░░░░██████████░░█████░██████░░░░
 ███████░░░░░░░░░░████░░░░░░   ░████░░░████░░███░████░░░░████░░░░░███████░░░░████░░░░░░░██████░░░░░███░░░░████░░░
██████████████░░░░ ░░░░░░░░░    ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  ░░░░░░░░░░░░░░░░░░░░   ░░░░░░░░░░░░░░░░░░░░░░░░
████░█████████░░    ░░░░░░░░     ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  ░░░░░░░░░░░░░░░░░░░    ░░░░░░░░░░░░░░░░░░░░░░░░
 ░░░░░░░░░░░░░░░     ░░░░░░       ░░░░░░░░░░░░░░░░░░░░░░░░░ ░░░░░  ░░░░░░░░░░░░ ░░░░░     ░░░░░░░░░░  ░░░░░ ░░░░░░
  ░░░░░░░░░░░░░░░     ░░░░          ░░░░   ░░░░  ░░░ ░░░░    ░░░░     ░░░░░░░    ░░░░       ░░░░░░     ░░░    ░░░░
   ░░░░░░░░░░░░░░░
    ░░░░ ░░░░░░░░░
```

**Taxgrok** is a powerful unified suite for tracking Solana crypto taxes and generating intelligent tax briefings from your documents using xAI. 

It features a stunning Web GUI Dashboard alongside a terminal CLI app for power users.

## 🌟 The Web GUI Dashboard (Solana Tax Tracker)

The `solana-tax-tracker` directory houses our beautiful, single-file PHP web application. It serves as your primary hub for Solana activity tracking and AI tax analysis.

### Dashboard Features
- **Taxgrok AI Document Analysis** — Upload your `.pdf` or `.png` tax forms (W-2s, 1099s, etc.) directly in the browser. Provide your `console.x.ai` API Key, select your filing status, and Taxgrok uses xAI's visual and text reasoning models to dynamically generate a formatted markdown brief offering refund estimates and checklist points. Click **"Export PDF"** for a clean, printable document.
- **Solana Multi-Wallet Tracking** — Add unlimited Solana wallet addresses. One-click sync pulls parsed historical transaction data (Swaps, Transfers, NFT mints/sales) securely via the Helius RPC.
- **Local SQLite Persistence** — All your crypto transaction data and wallet labels are stored securely on your local machine in the `soltracker.db` ledger.
- **CSV Export Engine** — Instantly filter your transaction ledgers and export them natively to CSV for easy handoff to TurboTax or your tax professional.

### How to Run the Web UI

**⚠️ Important:** The web dashboard *requires* the `taxgrok` python module to be installed on your machine so it can execute the xAI analysis pipeline in the background.

1. **Install the Python Engine**: Open a terminal in the root directory and install `taxgrok`:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install .
   ```
2. **Configure API Keys**: Create a `.env` file in the `solana-tax-tracker` directory:
   ```ini
   HELIUS_API_KEY="your_helius_key_here"  # Get a free key from helius.dev
   XAI_API_KEY="your_xai_key_here"        # Optional: Can also be inputted directly in the UI
   ```
3. **Start the Integrated Server**: Boot up the PHP development server inside the `solana-tax-tracker` directory:
   ```bash
   cd solana-tax-tracker
   php -S localhost:8000
   ```
4. **Launch**: Access the dashboard at [http://localhost:8000](http://localhost:8000). The `soltracker.db` ledger will initialize automatically!

---

## 💻 Terminal CLI App

If you prefer to skip the Web UI, Taxgrok also comes with a fully-featured interactive terminal application for document analysis!

### How to Run the CLI

1. **Activate the Environment & Install**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install .
   ```
2. **Export your xAI Key**:
   ```bash
   export XAI_API_KEY="your-xai-api-key"
   ```
3. **Run Taxgrok**:
   ```bash
   taxgrok
   ```

*(An interactive menu will guide you through adding files or entire folders for local RAG tax analysis).*

---

### Tech Stack
- **Python 3.9+** — The powerful local analysis tool integrating `pypdf` for PII redaction and inference interactions.
- **PHP 8.0+** — Single file web-app architecture powering the Solana Tracker UI.
- **SQLite** — Embedded zero-config offline wallet ledgering.

*Note: This tool is for educational planning and organization, not legal or tax advice.*
